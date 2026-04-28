from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
import requests

import image_search


def _png_bytes(size: tuple[int, int] = (640, 480), color: str = "navy") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeResponse:
    def __init__(
        self,
        *,
        content: bytes = b"",
        json_data: dict | None = None,
        status_code: int = 200,
        url: str = "https://example.com",
    ):
        self.content = content
        self._json_data = json_data
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error: error for url: {self.url}")

    def json(self) -> dict:
        if self._json_data is None:
            raise ValueError("No JSON payload configured")
        return self._json_data


class _SuccessfulDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def images(self, query: str, max_results: int = 5):
        return [{
            "image": "https://example.com/dna-storage.png",
            "thumbnail": "https://example.com/dna-storage-thumb.png",
            "title": "DNA storage preview",
            "source": "Example Source",
            "url": "https://example.com/story",
            "width": 640,
            "height": 480,
        }]


class _FailingDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def images(self, query: str, max_results: int = 5):
        raise RuntimeError("403 Ratelimit")


class _NoopRateLimiter:
    def acquire(self, *, reason: str) -> None:
        return None

    def penalize(self, cooldown_seconds: float, *, reason: str) -> float:
        return 0.0


class _RecordingRateLimiter:
    def __init__(self):
        self.acquire_calls: list[str] = []
        self.penalty_calls: list[tuple[float, str]] = []

    def acquire(self, *, reason: str) -> None:
        self.acquire_calls.append(reason)

    def penalize(self, cooldown_seconds: float, *, reason: str) -> float:
        self.penalty_calls.append((cooldown_seconds, reason))
        return cooldown_seconds


@pytest.fixture(autouse=True)
def _reset_provider_env(monkeypatch):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_PROVIDER_ORDER", raising=False)
    monkeypatch.setattr(image_search, "_ddg_image_rate_limiter", _NoopRateLimiter())


def test_search_image_preview_returns_pixabay_metadata(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-test-key")

    def fake_get(url, **kwargs):
        assert url == image_search._PIXABAY_API_URL
        params = kwargs["params"]
        assert params["q"] == "dna storage high resolution professional"
        return _FakeResponse(
            json_data={
                "hits": [{
                    "pageURL": "https://pixabay.com/photos/dna-1/",
                    "previewURL": "https://cdn.example.com/dna-preview.jpg",
                    "largeImageURL": "https://cdn.example.com/dna-large.jpg",
                    "webformatURL": "https://cdn.example.com/dna-web.jpg",
                    "imageWidth": 1280,
                    "imageHeight": 960,
                    "user": "Jane Doe",
                    "user_id": 42,
                    "tags": "dna, storage, science",
                }]
            },
            url=url,
        )

    monkeypatch.setattr(image_search.requests, "get", fake_get)

    result = image_search.search_image_preview("dna storage")

    assert result["provider"] == "pixabay"
    assert result["query"] == "dna storage high resolution professional"
    assert result["thumbnail"] == "https://cdn.example.com/dna-preview.jpg"
    assert result["image"] == "https://cdn.example.com/dna-large.jpg"
    assert result["source"] == "Pixabay"
    assert result["source_url"] == "https://pixabay.com/photos/dna-1/"
    assert result["photographer_name"] == "Jane Doe"
    assert result["license_label"] == "Pixabay Content License"
    assert result["attribution_text"] == "Image by Jane Doe on Pixabay"


def test_search_and_download_image_returns_pixabay_source_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-test-key")
    img_data = _png_bytes()

    def fake_get(url, **kwargs):
        if url == image_search._PIXABAY_API_URL:
            return _FakeResponse(
                json_data={
                    "hits": [{
                        "pageURL": "https://pixabay.com/photos/dna-1/",
                        "previewURL": "https://cdn.example.com/dna-preview.jpg",
                        "largeImageURL": "https://cdn.example.com/dna-large.jpg",
                        "imageWidth": 1280,
                        "imageHeight": 960,
                        "user": "Jane Doe",
                        "user_id": 42,
                        "tags": "dna, storage, science",
                    }]
                },
                url=url,
            )
        if url == "https://cdn.example.com/dna-large.jpg":
            return _FakeResponse(content=img_data, url=url)
        raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(image_search.requests, "get", fake_get)

    result = image_search.search_and_download_image("dna storage", output_dir=str(tmp_path))

    assert Path(result["path"]).exists()
    assert result["provider"] == "pixabay"
    assert result["url"] == "https://cdn.example.com/dna-large.jpg"
    assert result["source_url"] == "https://pixabay.com/photos/dna-1/"
    assert result["source"] == "Pixabay"
    assert result["selection_reason"] == "validated_image_search_result"
    assert result["query"] == "dna storage high resolution professional"
    assert result["mime_type"] == "image/jpeg"
    assert result["width"] == 640
    assert result["height"] == 480
    assert result["photographer_name"] == "Jane Doe"
    assert result["license_label"] == "Pixabay Content License"
    assert result["attribution_text"] == "Image by Jane Doe on Pixabay"


def test_search_image_preview_falls_back_to_pexels_for_photo_queries(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-test-key")
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-test-key")
    calls: list[str] = []

    def fake_get(url, **kwargs):
        if url == image_search._PIXABAY_API_URL:
            calls.append("pixabay")
            return _FakeResponse(json_data={"hits": []}, url=url)
        if url == image_search._PEXELS_API_URL:
            calls.append("pexels")
            return _FakeResponse(
                json_data={
                    "photos": [{
                        "width": 1600,
                        "height": 900,
                        "url": "https://www.pexels.com/photo/robotics-lab-123/",
                        "photographer": "Alex Smith",
                        "photographer_url": "https://www.pexels.com/@alex-smith/",
                        "alt": "Humanoid robotics lab",
                        "src": {
                            "medium": "https://images.pexels.com/photos/123/medium.jpeg",
                            "large": "https://images.pexels.com/photos/123/large.jpeg",
                            "large2x": "https://images.pexels.com/photos/123/large2x.jpeg",
                        },
                    }]
                },
                url=url,
            )
        raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(image_search.requests, "get", fake_get)

    result = image_search.search_image_preview("humanoid robotics lab photo")

    assert "pixabay" in calls
    assert calls[-1] == "pexels"
    assert calls.count("pexels") == 1
    assert result["provider"] == "pexels"
    assert result["source"] == "Pexels"
    assert result["source_url"] == "https://www.pexels.com/photo/robotics-lab-123/"
    assert result["photographer_name"] == "Alex Smith"
    assert result["license_label"] == "Pexels License"
    assert result["attribution_text"] == "Photo by Alex Smith on Pexels"


def test_search_and_download_image_falls_back_to_serpapi_for_niche_queries(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-test-key")
    monkeypatch.setenv("SERPAPI_API_KEY", "serpapi-test-key")
    img_data = _png_bytes(color="green")
    calls: list[str] = []

    def fake_get(url, **kwargs):
        if url == image_search._PIXABAY_API_URL:
            calls.append("pixabay")
            return _FakeResponse(json_data={"hits": []}, url=url)
        if url == image_search._SERPAPI_API_URL:
            calls.append("serpapi")
            return _FakeResponse(
                json_data={
                    "images_results": [{
                        "thumbnail": "https://serpapi.example.com/thumb.jpeg",
                        "original": "https://cdn.example.com/workflow.png",
                        "original_width": 1400,
                        "original_height": 900,
                        "title": "DNA workflow schematic",
                        "link": "https://example.com/workflow-article",
                        "source": "Example.com",
                    }]
                },
                url=url,
            )
        if url == "https://cdn.example.com/workflow.png":
            return _FakeResponse(content=img_data, url=url)
        raise AssertionError(f"Unexpected URL fetched: {url}")

    monkeypatch.setattr(image_search.requests, "get", fake_get)

    result = image_search.search_and_download_image(
        "dna storage workflow schematic",
        output_dir=str(tmp_path),
    )

    assert "pixabay" in calls
    assert calls[-1] == "serpapi"
    assert calls.count("serpapi") == 1
    assert result["provider"] == "serpapi"
    assert result["source"] == "Example.com"
    assert result["source_url"] == "https://example.com/workflow-article"
    assert result["license_label"] == "Third-party source"
    assert result["attribution_text"] == "Source: Example.com"


def test_search_image_preview_uses_ddgs_when_no_api_keys_configured(monkeypatch):
    monkeypatch.setattr(image_search, "_new_ddgs", lambda: _SuccessfulDDGS())

    result = image_search.search_image_preview("dna storage")

    assert result["provider"] == "ddgs"
    assert result["query"] == "dna storage high resolution professional"
    assert result["thumbnail"] == "https://example.com/dna-storage-thumb.png"
    assert result["source_url"] == "https://example.com/story"


def test_search_image_preview_returns_error_on_ddgs_rate_limit(monkeypatch):
    limiter = _RecordingRateLimiter()
    monkeypatch.setattr(image_search, "_new_ddgs", lambda: _FailingDDGS())
    monkeypatch.setattr(image_search, "_ddg_image_rate_limiter", limiter)

    result = image_search.search_image_preview("dna storage")

    assert "error" in result
    assert result["provider"] == "image_search"
    assert limiter.acquire_calls == ["image query 'dna storage high resolution professional'"]
    assert limiter.penalty_calls == [
        (image_search._DDG_IMAGE_SEARCH_COOLDOWN_SECONDS, "403 Ratelimit")
    ]


def test_search_and_download_image_uses_placeholder_only_when_explicit(monkeypatch, tmp_path: Path):
    placeholder_path = tmp_path / "placeholder.png"
    Image.new("RGB", (640, 480), color="gray").save(placeholder_path)

    monkeypatch.setattr(image_search, "_new_ddgs", lambda: _FailingDDGS())
    monkeypatch.setattr(image_search.time, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        image_search,
        "generate_placeholder_image",
        lambda query, output_dir: {
            "path": str(placeholder_path),
            "url": "placeholder",
            "source_url": "placeholder",
            "filename": placeholder_path.name,
        },
    )

    result = image_search.search_and_download_image(
        "dna storage",
        output_dir=str(tmp_path),
        allow_placeholder_fallback=True,
    )

    assert result["path"] == str(placeholder_path)
    assert result["provider"] == "placeholder"
    assert result["query"] == "dna storage"
    assert result["selection_reason"] == "explicit_placeholder_fallback"


def test_search_and_download_image_returns_error_without_explicit_placeholder(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(image_search, "_new_ddgs", lambda: _FailingDDGS())
    monkeypatch.setattr(image_search.time, "sleep", lambda *args, **kwargs: None)

    result = image_search.search_and_download_image(
        "dna storage",
        output_dir=str(tmp_path),
        allow_placeholder_fallback=False,
    )

    assert "error" in result
    assert result["provider"] == "image_search"
    assert result["query"] == "dna storage"
