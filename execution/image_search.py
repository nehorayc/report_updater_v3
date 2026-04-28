try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - compatibility fallback
    from duckduckgo_search import DDGS
import hashlib
import os
import threading
import time
import uuid
import warnings
from io import BytesIO
from urllib.parse import urlparse

import requests

from logger_config import setup_logger

logger = setup_logger("ImageSearch")

_PROVIDER_DISPLAY_NAMES = {
    "pixabay": "Pixabay",
    "pexels": "Pexels",
    "serpapi": "SerpApi",
    "ddgs": "DuckDuckGo",
    "placeholder": "Placeholder",
}
_PROVIDER_API_KEY_ENVS = {
    "pixabay": "PIXABAY_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
}
_DEFAULT_PROVIDER_ORDER = ("pixabay", "pexels", "serpapi")
_ILLUSTRATION_HINTS = {
    "architecture",
    "comparison",
    "concept",
    "diagram",
    "ecosystem",
    "flowchart",
    "illustration",
    "infographic",
    "schematic",
    "timeline",
    "workflow",
}
_BLOCKED_DOWNLOAD_DOMAINS = {
    "researchgate.net",
}
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}
_PIXABAY_API_URL = "https://pixabay.com/api/"
_PEXELS_API_URL = "https://api.pexels.com/v1/search"
_SERPAPI_API_URL = "https://serpapi.com/search.json"


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s value %r. Falling back to %.2f.", name, raw, default)
        return default


_IMAGE_SEARCH_TIMEOUT_SECONDS = _float_env("IMAGE_SEARCH_TIMEOUT_SECONDS", 15.0)
_DDG_IMAGE_SEARCH_MIN_INTERVAL_SECONDS = _float_env(
    "DDG_IMAGE_SEARCH_MIN_INTERVAL_SECONDS",
    1.0,
)
_DDG_IMAGE_SEARCH_COOLDOWN_SECONDS = _float_env(
    "DDG_IMAGE_SEARCH_COOLDOWN_SECONDS",
    5.0,
)


class _SearchRateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def acquire(self, *, reason: str) -> None:
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_allowed_at - now)
            self._next_allowed_at = max(self._next_allowed_at, now) + self.min_interval_seconds

        if wait_seconds > 0:
            logger.info(
                "Throttling DDG image search for %.2fs before %s.",
                wait_seconds,
                reason,
            )
            time.sleep(wait_seconds)

    def penalize(self, cooldown_seconds: float, *, reason: str) -> float:
        cooldown_seconds = max(0.0, float(cooldown_seconds))
        if cooldown_seconds <= 0:
            return 0.0

        with self._lock:
            now = time.monotonic()
            self._next_allowed_at = max(self._next_allowed_at, now + cooldown_seconds)
            cooldown_until = self._next_allowed_at

        enforced_cooldown = max(0.0, cooldown_until - time.monotonic())
        logger.warning(
            "DDG image search cooldown extended by %.2fs after provider throttling: %s",
            enforced_cooldown,
            reason,
        )
        return enforced_cooldown


_ddg_image_rate_limiter = _SearchRateLimiter(_DDG_IMAGE_SEARCH_MIN_INTERVAL_SECONDS)


def _new_ddgs():
    original_warn = warnings.warn

    def _warn(message, *args, **kwargs):
        if "has been renamed to `ddgs`" in str(message):
            return None
        return original_warn(message, *args, **kwargs)

    warnings.warn = _warn
    try:
        return DDGS()
    finally:
        warnings.warn = original_warn


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(str(provider or "").strip().lower(), str(provider or "").strip() or "Unknown")


def _provider_api_key(provider: str) -> str:
    env_name = _PROVIDER_API_KEY_ENVS.get(str(provider or "").strip().lower())
    if not env_name:
        return ""
    return str(os.getenv(env_name) or "").strip()


def _configured_provider_order() -> list[str]:
    raw = str(os.getenv("IMAGE_PROVIDER_ORDER") or "").strip()
    if raw:
        providers = []
        for token in raw.split(","):
            provider = token.strip().lower()
            if provider and provider in (*_DEFAULT_PROVIDER_ORDER, "ddgs") and provider not in providers:
                providers.append(provider)
    else:
        providers = list(_DEFAULT_PROVIDER_ORDER)

    if not providers:
        providers = list(_DEFAULT_PROVIDER_ORDER)

    if "ddgs" not in providers and not any(_provider_api_key(provider) for provider in providers):
        providers.append("ddgs")

    return providers


def _domain_from_url(value: str) -> str:
    domain = urlparse(str(value or "").strip()).netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


def _blocked_download_url(value: str) -> bool:
    domain = _domain_from_url(value)
    if not domain:
        return False
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in _BLOCKED_DOWNLOAD_DOMAINS)


def _query_prefers_non_photo(query: str) -> bool:
    normalized = " ".join(str(query or "").lower().split())
    return any(token in normalized for token in _ILLUSTRATION_HINTS)


def _preferred_pixabay_image_types(query: str) -> list[str]:
    if _query_prefers_non_photo(query):
        return ["illustration", "vector", "all"]
    return ["photo", "all"]


def _provider_enabled_for_query(provider: str, query: str) -> bool:
    if provider == "pexels" and _query_prefers_non_photo(query):
        return False
    return True


def _image_mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _aspect_ratio(width: int, height: int) -> float:
    if not width or not height:
        return 0.0
    return round(width / height, 4)


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _request_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=_IMAGE_SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Image provider returned a non-object JSON response")
    return payload


def _build_attribution_text(
    provider: str,
    *,
    photographer_name: str = "",
    source: str = "",
    source_url: str = "",
) -> str:
    provider_label = _provider_display_name(provider)
    photographer_name = str(photographer_name or "").strip()
    source = str(source or "").strip()
    source_url = str(source_url or "").strip()

    if photographer_name:
        prefix = "Photo" if provider == "pexels" else "Image"
        return f"{prefix} by {photographer_name} on {provider_label}"
    if provider in {"pixabay", "pexels"}:
        return f"Source: {provider_label}"
    if source:
        return f"Source: {source}"
    if source_url:
        domain = _domain_from_url(source_url)
        if domain:
            return f"Source: {domain}"
    return ""


def _normalize_candidate(
    *,
    provider: str,
    query: str,
    image: str,
    thumbnail: str = "",
    download_url: str = "",
    title: str = "",
    source: str = "",
    source_url: str = "",
    width=None,
    height=None,
    photographer_name: str = "",
    photographer_url: str = "",
    license_label: str = "",
    attribution_text: str = "",
) -> dict | None:
    image = str(image or "").strip()
    thumbnail = str(thumbnail or "").strip()
    download_url = str(download_url or image).strip()
    source_url = str(source_url or download_url).strip()
    title = " ".join(str(title or "").split()).strip() or " ".join(str(query or "").split()).strip()
    source = " ".join(str(source or "").split()).strip()
    photographer_name = " ".join(str(photographer_name or "").split()).strip()
    photographer_url = str(photographer_url or "").strip()
    license_label = " ".join(str(license_label or "").split()).strip()

    if not image and not thumbnail:
        return None

    if not attribution_text:
        attribution_text = _build_attribution_text(
            provider,
            photographer_name=photographer_name,
            source=source,
            source_url=source_url,
        )

    return {
        "provider": provider,
        "query": query,
        "image": image or thumbnail,
        "thumbnail": thumbnail or image,
        "download_url": download_url or image or thumbnail,
        "title": title,
        "source": source,
        "source_url": source_url,
        "width": _int_or_none(width),
        "height": _int_or_none(height),
        "photographer_name": photographer_name,
        "photographer_url": photographer_url,
        "license_label": license_label,
        "attribution_text": attribution_text,
    }


def _pixabay_user_url(hit: dict) -> str:
    user = str(hit.get("user") or "").strip()
    user_id = hit.get("user_id")
    if user and user_id not in (None, ""):
        return f"https://pixabay.com/users/{user}-{user_id}/"
    return ""


def _pixabay_candidate(hit: dict, *, query: str) -> dict | None:
    title = str(hit.get("tags") or query or "").strip()
    return _normalize_candidate(
        provider="pixabay",
        query=query,
        image=str(hit.get("largeImageURL") or hit.get("webformatURL") or hit.get("previewURL") or ""),
        thumbnail=str(hit.get("previewURL") or hit.get("webformatURL") or ""),
        download_url=str(hit.get("largeImageURL") or hit.get("webformatURL") or hit.get("previewURL") or ""),
        title=title,
        source="Pixabay",
        source_url=str(hit.get("pageURL") or ""),
        width=hit.get("imageWidth") or hit.get("webformatWidth"),
        height=hit.get("imageHeight") or hit.get("webformatHeight"),
        photographer_name=str(hit.get("user") or ""),
        photographer_url=_pixabay_user_url(hit),
        license_label="Pixabay Content License",
    )


def _search_pixabay_results(query_variants: list[str], *, max_results: int = 5) -> tuple[list[dict], str]:
    api_key = _provider_api_key("pixabay")
    if not api_key:
        raise RuntimeError("Pixabay API key not configured")

    last_query = query_variants[0] if query_variants else ""
    for variant in query_variants:
        last_query = variant
        candidates = []
        seen = set()
        for image_type in _preferred_pixabay_image_types(variant):
            payload = _request_json(
                _PIXABAY_API_URL,
                params={
                    "key": api_key,
                    "q": variant,
                    "lang": "en",
                    "per_page": max_results,
                    "safesearch": "true",
                    "image_type": image_type,
                },
            )
            hits = payload.get("hits") or []
            for hit in hits:
                candidate = _pixabay_candidate(hit, query=variant)
                if not candidate:
                    continue
                dedupe_key = candidate.get("source_url") or candidate.get("download_url")
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                candidates.append(candidate)
            if candidates:
                return candidates[:max_results], variant
    return [], last_query


def _pexels_candidate(photo: dict, *, query: str) -> dict | None:
    src = photo.get("src") or {}
    return _normalize_candidate(
        provider="pexels",
        query=query,
        image=str(src.get("large") or src.get("large2x") or src.get("original") or src.get("medium") or ""),
        thumbnail=str(src.get("medium") or src.get("small") or src.get("tiny") or ""),
        download_url=str(src.get("large2x") or src.get("large") or src.get("original") or src.get("medium") or ""),
        title=str(photo.get("alt") or query or ""),
        source="Pexels",
        source_url=str(photo.get("url") or ""),
        width=photo.get("width"),
        height=photo.get("height"),
        photographer_name=str(photo.get("photographer") or ""),
        photographer_url=str(photo.get("photographer_url") or ""),
        license_label="Pexels License",
    )


def _search_pexels_results(query_variants: list[str], *, max_results: int = 5) -> tuple[list[dict], str]:
    api_key = _provider_api_key("pexels")
    if not api_key:
        raise RuntimeError("Pexels API key not configured")

    headers = {"Authorization": api_key}
    last_query = query_variants[0] if query_variants else ""
    for variant in query_variants:
        last_query = variant
        payload = _request_json(
            _PEXELS_API_URL,
            params={"query": variant, "per_page": max_results, "page": 1},
            headers=headers,
        )
        photos = payload.get("photos") or []
        candidates = []
        seen = set()
        for photo in photos:
            candidate = _pexels_candidate(photo, query=variant)
            if not candidate:
                continue
            dedupe_key = candidate.get("source_url") or candidate.get("download_url")
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)
        if candidates:
            return candidates[:max_results], variant
    return [], last_query


def _serpapi_candidate(result: dict, *, query: str) -> dict | None:
    source_url = str(result.get("link") or "")
    source_name = str(result.get("source") or _domain_from_url(source_url) or "Web")
    return _normalize_candidate(
        provider="serpapi",
        query=query,
        image=str(result.get("original") or result.get("thumbnail") or ""),
        thumbnail=str(result.get("thumbnail") or result.get("original") or ""),
        download_url=str(result.get("original") or result.get("thumbnail") or ""),
        title=str(result.get("title") or query or ""),
        source=source_name,
        source_url=source_url,
        width=result.get("original_width"),
        height=result.get("original_height"),
        license_label="Third-party source",
    )


def _search_serpapi_results(query_variants: list[str], *, max_results: int = 5) -> tuple[list[dict], str]:
    api_key = _provider_api_key("serpapi")
    if not api_key:
        raise RuntimeError("SerpApi key not configured")

    last_query = query_variants[0] if query_variants else ""
    for variant in query_variants:
        last_query = variant
        payload = _request_json(
            _SERPAPI_API_URL,
            params={
                "api_key": api_key,
                "engine": "google_images",
                "q": variant,
                "safe": "active",
                "gl": "us",
                "hl": "en",
                "num": max_results,
            },
        )
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        results = payload.get("images_results") or payload.get("image_results") or []
        candidates = []
        seen = set()
        for result in results:
            candidate = _serpapi_candidate(result, query=variant)
            if not candidate:
                continue
            dedupe_key = candidate.get("source_url") or candidate.get("download_url")
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)
        if candidates:
            return candidates[:max_results], variant
    return [], last_query


def _ddgs_candidate(result: dict, *, query: str) -> dict | None:
    source_url = str(result.get("url") or result.get("image") or "")
    return _normalize_candidate(
        provider="ddgs",
        query=query,
        image=str(result.get("image") or result.get("thumbnail") or ""),
        thumbnail=str(result.get("thumbnail") or result.get("image") or ""),
        download_url=str(result.get("image") or result.get("thumbnail") or ""),
        title=str(result.get("title") or query or ""),
        source=str(result.get("source") or _domain_from_url(source_url) or "Web"),
        source_url=source_url,
        width=result.get("width"),
        height=result.get("height"),
        license_label="Third-party source",
    )


def _search_ddgs_results(query_variants: list[str], *, max_results: int = 5) -> tuple[list[dict], str]:
    last_error = "No image results found"
    for variant in query_variants:
        _ddg_image_rate_limiter.acquire(reason=f"image query {variant!r}")
        try:
            with _new_ddgs() as ddgs:
                results = ddgs.images(variant, max_results=max_results)
                results_list = list(results)
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                _ddg_image_rate_limiter.penalize(
                    _DDG_IMAGE_SEARCH_COOLDOWN_SECONDS,
                    reason=str(exc),
                )
            raise

        candidates = []
        for result in results_list:
            candidate = _ddgs_candidate(result, query=variant)
            if candidate:
                candidates.append(candidate)
        if candidates:
            return candidates[:max_results], variant
        last_error = f"No images found for query variant: {variant}"

    return [], last_error


def _enrich_saved_image_metadata(
    *,
    path: str,
    filename: str,
    img_url: str,
    query: str,
    provider: str,
    selection_reason: str,
    width: int,
    height: int,
    img_data: bytes,
    source_url: str = "",
    source: str = "",
    title: str = "",
    thumbnail: str = "",
    photographer_name: str = "",
    photographer_url: str = "",
    license_label: str = "",
    attribution_text: str = "",
) -> dict:
    return {
        "path": path,
        "url": img_url,
        "source_url": source_url or img_url,
        "filename": filename,
        "provider": provider,
        "query": query,
        "selection_reason": selection_reason,
        "content_hash": hashlib.sha256(img_data).hexdigest(),
        "mime_type": _image_mime_type(path),
        "width": width,
        "height": height,
        "aspect_ratio": _aspect_ratio(width, height),
        "source": source,
        "title": title,
        "thumbnail": thumbnail,
        "photographer_name": photographer_name,
        "photographer_url": photographer_url,
        "license_label": license_label,
        "attribution_text": attribution_text,
    }


def _query_variants(query: str) -> list[str]:
    cleaned = " ".join(str(query or "").split())
    if not cleaned:
        return []

    quality_suffix = "high resolution professional"
    variants = []
    enriched = cleaned if quality_suffix in cleaned.lower() else f"{cleaned} {quality_suffix}"
    for candidate in (enriched, cleaned):
        normalized = " ".join(candidate.split())
        if normalized and normalized not in variants:
            variants.append(normalized)
    return variants


def _is_rate_limit_error(message: str) -> bool:
    normalized = str(message or "").lower()
    return any(token in normalized for token in ("403", "429", "ratelimit", "rate limit", "quota"))


def _search_image_results(query: str, *, max_results: int = 5) -> tuple[list[str], list[dict], str]:
    query_variants = _query_variants(query)
    if not query_variants:
        return [], [], "Image search query is empty"

    providers = _configured_provider_order()
    provider_errors = []
    for provider in providers:
        if not _provider_enabled_for_query(provider, query):
            logger.info("Skipping provider %s for non-photo query '%s'.", provider, query)
            continue

        if provider != "ddgs" and not _provider_api_key(provider):
            provider_errors.append(f"{provider}: missing API key")
            continue

        try:
            logger.info("Searching images via %s for '%s'.", _provider_display_name(provider), query)
            if provider == "pixabay":
                results_list, resolved_query_or_error = _search_pixabay_results(query_variants, max_results=max_results)
            elif provider == "pexels":
                results_list, resolved_query_or_error = _search_pexels_results(query_variants, max_results=max_results)
            elif provider == "serpapi":
                results_list, resolved_query_or_error = _search_serpapi_results(query_variants, max_results=max_results)
            elif provider == "ddgs":
                results_list, resolved_query_or_error = _search_ddgs_results(query_variants, max_results=max_results)
            else:
                provider_errors.append(f"{provider}: unsupported provider")
                continue
        except Exception as exc:
            provider_errors.append(f"{provider}: {exc}")
            logger.warning(
                "Image search provider %s failed for '%s': %s",
                _provider_display_name(provider),
                query,
                exc,
            )
            continue

        if results_list:
            return query_variants, results_list, resolved_query_or_error
        provider_errors.append(f"{provider}: no results")

    last_error = "; ".join(provider_errors) if provider_errors else "No image results found"
    return query_variants, [], last_error


def search_image_preview(query: str) -> dict:
    """Return lightweight preview metadata for the top matching image result."""
    logger.info("Starting image preview search for: '%s'", query)
    try:
        query_variants, results_list, resolved_query_or_error = _search_image_results(query, max_results=5)
    except Exception as exc:
        logger.warning("Image preview search failed for '%s': %s", query, exc)
        return {"error": str(exc), "provider": "image_search", "query": query}
    if not query_variants:
        return {"error": resolved_query_or_error, "provider": "image_search", "query": query}
    if not results_list:
        return {"error": resolved_query_or_error, "provider": "image_search", "query": query_variants[0]}

    top_result = results_list[0]
    preview = {
        "provider": top_result.get("provider", "image_search"),
        "query": resolved_query_or_error,
        "selection_reason": "search_preview_result",
        "thumbnail": top_result.get("thumbnail"),
        "image": top_result.get("image"),
        "title": top_result.get("title", ""),
        "source": top_result.get("source", ""),
        "source_url": top_result.get("source_url") or top_result.get("image"),
        "width": top_result.get("width"),
        "height": top_result.get("height"),
        "photographer_name": top_result.get("photographer_name", ""),
        "photographer_url": top_result.get("photographer_url", ""),
        "license_label": top_result.get("license_label", ""),
        "attribution_text": top_result.get("attribution_text", ""),
    }
    if not preview["thumbnail"] and not preview["image"]:
        return {
            "error": "Image preview result did not contain a displayable URL",
            "provider": top_result.get("provider", "image_search"),
            "query": resolved_query_or_error,
        }
    return preview


def search_and_download_image(
    query: str,
    output_dir: str = ".tmp/visuals",
    *,
    allow_placeholder_fallback: bool = False,
) -> dict:
    """
    Search for an image and download the top result.
    Automatically enriches the query with quality keywords and
    filters out images smaller than 400x300 px.
    """
    logger.info("Starting image search for: '%s'", query)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    query_variants = _query_variants(query)
    if not query_variants:
        error = "Image search query is empty"
        logger.error(error)
        if allow_placeholder_fallback:
            placeholder = generate_placeholder_image(query or "Untitled visual", output_dir)
            placeholder["provider"] = "placeholder"
            placeholder["selection_reason"] = "empty_query_fallback"
            return placeholder
        return {"error": error}
    logger.info("Prepared image search queries: %s", query_variants)

    MAX_RETRIES = 3
    retry_count = 0
    backoff = 2
    last_error = "Unknown image search failure"

    start_time = time.time()

    while retry_count < MAX_RETRIES:
        try:
            _, results_list, resolved_query_or_error = _search_image_results(query, max_results=5)
            if not results_list:
                raise Exception(resolved_query_or_error or last_error)

            for i, candidate in enumerate(results_list[:3]):
                img_url = str(candidate.get("download_url") or candidate.get("image") or "").strip()
                if not img_url:
                    last_error = "Candidate did not include a downloadable image URL"
                    continue
                if _blocked_download_url(img_url) or _blocked_download_url(candidate.get("source_url")):
                    logger.info(
                        "Skipping provider result %s from blocked domain for '%s': %s",
                        i + 1,
                        resolved_query_or_error,
                        img_url,
                    )
                    last_error = f"Blocked source domain for {img_url}"
                    continue

                logger.info(
                    "Attempting to download result %s via %s for '%s': %s...",
                    i + 1,
                    _provider_display_name(candidate.get("provider", "")),
                    resolved_query_or_error,
                    img_url[:60],
                )

                try:
                    download_start = time.time()
                    response = requests.get(
                        img_url,
                        timeout=_IMAGE_SEARCH_TIMEOUT_SECONDS,
                        headers=_REQUEST_HEADERS,
                    )
                    response.raise_for_status()
                    img_data = response.content

                    from PIL import Image

                    try:
                        img = Image.open(BytesIO(img_data))
                        img.verify()
                        img = Image.open(BytesIO(img_data))
                        width, height = img.size
                        if width < 400 or height < 300:
                            logger.warning("Result %s too small (%sx%s), skipping.", i + 1, width, height)
                            last_error = f"Image too small: {width}x{height}"
                            continue
                        logger.info("Successfully validated image from result %s (%sx%s)", i + 1, width, height)
                    except Exception as ve:
                        logger.warning("Result %s failed image validation: %s", i + 1, ve)
                        last_error = f"Image validation failed: {ve}"
                        continue

                    download_latency = time.time() - download_start
                    logger.debug("Image downloaded in %.2fs.", download_latency)

                    ext = img_url.split(".")[-1].split("?")[0].lower()
                    if ext not in ["jpg", "jpeg", "png", "gif", "bmp", "webp"]:
                        ext = "png"

                    filename = f"search_{uuid.uuid4().hex}.{ext}"
                    path = os.path.join(output_dir, filename)

                    with open(path, "wb") as f:
                        f.write(img_data)

                    latency = time.time() - start_time
                    logger.info("Image search and download complete in %.2fs. Saved to %s", latency, path)
                    return _enrich_saved_image_metadata(
                        path=path,
                        filename=filename,
                        img_url=img_url,
                        query=resolved_query_or_error,
                        provider=str(candidate.get("provider") or "image_search"),
                        selection_reason="validated_image_search_result",
                        width=width,
                        height=height,
                        img_data=img_data,
                        source_url=str(candidate.get("source_url") or ""),
                        source=str(candidate.get("source") or ""),
                        title=str(candidate.get("title") or ""),
                        thumbnail=str(candidate.get("thumbnail") or ""),
                        photographer_name=str(candidate.get("photographer_name") or ""),
                        photographer_url=str(candidate.get("photographer_url") or ""),
                        license_label=str(candidate.get("license_label") or ""),
                        attribution_text=str(candidate.get("attribution_text") or ""),
                    )
                except Exception as de:
                    logger.warning("Failed to process result %s: %s", i + 1, de)
                    last_error = str(de)
                    continue

            raise Exception(last_error or "Found results but none were valid images.")

        except Exception as e:
            retry_count += 1
            last_error = str(e)
            logger.warning("Image search attempt %s/%s failed for '%s': %s", retry_count, MAX_RETRIES, query, e)
            if retry_count >= MAX_RETRIES:
                logger.error("Max retries reached for image search '%s'. Skipping visual.", query)
                if allow_placeholder_fallback:
                    placeholder = generate_placeholder_image(query, output_dir)
                    placeholder["provider"] = "placeholder"
                    placeholder["query"] = query
                    placeholder["selection_reason"] = "explicit_placeholder_fallback"
                    return placeholder
                return {"error": f"Image search failed after {MAX_RETRIES} attempts: {e}", "provider": "image_search", "query": query}

            sleep_time = backoff * retry_count
            logger.info("Retrying in %ss...", sleep_time)
            time.sleep(sleep_time)

    if allow_placeholder_fallback:
        placeholder = generate_placeholder_image(query, output_dir)
        placeholder["provider"] = "placeholder"
        placeholder["query"] = query
        placeholder["selection_reason"] = "explicit_placeholder_fallback"
        return placeholder
    return {"error": "Image search exhausted all retries.", "provider": "image_search", "query": query}


def generate_placeholder_image(query: str, output_dir: str) -> dict:
    """
    Generates a simple placeholder image with text using matplotlib.
    """
    try:
        import matplotlib.pyplot as plt
        import textwrap
        from PIL import Image

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = f"placeholder_{uuid.uuid4().hex}.png"
        path = os.path.join(output_dir, filename)

        plt.figure(figsize=(10, 6))
        plt.text(
            0.5,
            0.5,
            f"Image Not Found\n\nQuery: {textwrap.fill(query, 30)}",
            ha="center",
            va="center",
            fontsize=20,
            color="gray",
        )
        plt.axis("off")
        plt.savefig(path, bbox_inches="tight", pad_inches=0.5)
        plt.close()

        logger.info("Generated placeholder image at %s", path)
        with Image.open(path) as placeholder_image:
            width, height = placeholder_image.size
        return {
            "path": path,
            "url": "placeholder",
            "source_url": "placeholder",
            "filename": filename,
            "mime_type": _image_mime_type(path),
            "width": width,
            "height": height,
            "aspect_ratio": _aspect_ratio(width, height),
            "source": "Placeholder",
            "license_label": "Generated placeholder",
            "attribution_text": "Generated placeholder image",
        }
    except Exception as e:
        logger.error("Failed to generate placeholder: %s", e)
        return {"error": "Failed to generate placeholder"}


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "clean energy turbine"
    print(search_and_download_image(q))
