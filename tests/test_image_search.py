from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

import image_search


def _png_bytes(size: tuple[int, int] = (640, 480), color: str = "navy") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _SuccessfulDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def images(self, query: str, max_results: int = 5):
        return [{"image": "https://example.com/dna-storage.png"}]


class _FailingDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def images(self, query: str, max_results: int = 5):
        raise RuntimeError("403 Ratelimit")


def test_search_and_download_image_returns_source_metadata(monkeypatch, tmp_path: Path):
    img_data = _png_bytes()

    monkeypatch.setattr(image_search, "_new_ddgs", lambda: _SuccessfulDDGS())
    monkeypatch.setattr(
        image_search.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(img_data),
    )

    result = image_search.search_and_download_image("dna storage", output_dir=str(tmp_path))

    assert Path(result["path"]).exists()
    assert result["provider"] == "ddgs"
    assert result["url"] == "https://example.com/dna-storage.png"
    assert result["source_url"] == result["url"]
    assert result["selection_reason"] == "validated_image_search_result"
    assert result["query"] == "dna storage high resolution professional"
    assert result["mime_type"] == "image/png"
    assert result["width"] == 640
    assert result["height"] == 480
    assert result["aspect_ratio"] == round(640 / 480, 4)
    assert result["content_hash"] == hashlib.sha256(img_data).hexdigest()


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
    assert result["provider"] == "ddgs"
    assert result["query"] == "dna storage"
