import logging
import os
import threading
import time
import warnings
from typing import Any, Iterable


try:
    from google import genai as _modern_genai
    from google.genai import types as _modern_types

    SDK_FLAVOR = "google-genai"
except ImportError:
    _modern_genai = None
    _modern_types = None
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*google\\.generativeai.*",
            category=FutureWarning,
        )
        import google.generativeai as _legacy_genai  # type: ignore

    SDK_FLAVOR = "google-generativeai"


def _normalize_contents(contents: Any) -> Any:
    if SDK_FLAVOR != "google-genai" or _modern_types is None:
        return contents

    if not isinstance(contents, list):
        return contents

    normalized = []
    for item in contents:
        if isinstance(item, dict) and {"mime_type", "data"}.issubset(item.keys()):
            normalized.append(
                _modern_types.Part.from_bytes(
                    data=item["data"],
                    mime_type=item["mime_type"],
                )
            )
        else:
            normalized.append(item)
    return normalized


_TRANSIENT_HTTP_STATUS_CODES = (408, 429, 500, 502, 503, 504)
_DEFAULT_RETRY_ATTEMPTS = 4
_DEFAULT_RETRY_INITIAL_DELAY_SECONDS = 1.0
_DEFAULT_RETRY_MAX_DELAY_SECONDS = 20.0
_DEFAULT_RETRY_EXP_BASE = 2.0
_DEFAULT_RETRY_JITTER = 1.0
_DEFAULT_MAX_CONCURRENT_REQUESTS = 1
_DEFAULT_MIN_INTERVAL_SECONDS = 1.0
_REQUEST_SLOT_POLL_INTERVAL_SECONDS = 0.05
_FLASH3_HIGH_DEMAND_FALLBACK_MODEL = "gemini-2.5-flash"
_FLASH25_HIGH_DEMAND_FALLBACK_MODEL = "gemini-2.0-flash"


logger = logging.getLogger(__name__)


# Shared gate for all Gemini calls in this Python process. This lets us smooth
# request bursts even if future code paths add threads or parallel workers.
_REQUEST_GATE = threading.Condition()
_ACTIVE_REQUESTS = 0
_NEXT_REQUEST_NOT_BEFORE = 0.0


def _get_env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    if minimum is not None and value < minimum:
        return minimum
    return value


def _get_env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default

    try:
        value = float(raw)
    except ValueError:
        return default

    if minimum is not None and value < minimum:
        return minimum
    return value


def _build_http_options() -> Any:
    if SDK_FLAVOR != "google-genai" or _modern_types is None:
        return None

    attempts = _get_env_int("GEMINI_RETRY_ATTEMPTS", _DEFAULT_RETRY_ATTEMPTS, minimum=1)
    if attempts <= 1:
        return None

    initial_delay = _get_env_float(
        "GEMINI_RETRY_INITIAL_DELAY_SECONDS",
        _DEFAULT_RETRY_INITIAL_DELAY_SECONDS,
        minimum=0.0,
    )
    max_delay = _get_env_float(
        "GEMINI_RETRY_MAX_DELAY_SECONDS",
        _DEFAULT_RETRY_MAX_DELAY_SECONDS,
        minimum=initial_delay,
    )
    exp_base = _get_env_float(
        "GEMINI_RETRY_EXP_BASE",
        _DEFAULT_RETRY_EXP_BASE,
        minimum=1.0,
    )
    jitter = _get_env_float(
        "GEMINI_RETRY_JITTER",
        _DEFAULT_RETRY_JITTER,
        minimum=0.0,
    )

    return _modern_types.HttpOptions(
        retry_options=_modern_types.HttpRetryOptions(
            attempts=attempts,
            initial_delay=initial_delay,
            max_delay=max_delay,
            exp_base=exp_base,
            jitter=jitter,
            http_status_codes=list(_TRANSIENT_HTTP_STATUS_CODES),
        )
    )


def _rate_limit_settings() -> tuple[int, float]:
    max_concurrent = _get_env_int(
        "GEMINI_MAX_CONCURRENT_REQUESTS",
        _DEFAULT_MAX_CONCURRENT_REQUESTS,
        minimum=1,
    )
    min_interval = _get_env_float(
        "GEMINI_MIN_INTERVAL_SECONDS",
        _DEFAULT_MIN_INTERVAL_SECONDS,
        minimum=0.0,
    )
    return max_concurrent, min_interval


def _now() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _acquire_request_slot() -> None:
    max_concurrent, min_interval = _rate_limit_settings()
    global _ACTIVE_REQUESTS
    global _NEXT_REQUEST_NOT_BEFORE

    while True:
        wait_seconds = 0.0
        with _REQUEST_GATE:
            now = _now()
            if _ACTIVE_REQUESTS < max_concurrent and now >= _NEXT_REQUEST_NOT_BEFORE:
                _ACTIVE_REQUESTS += 1
                _NEXT_REQUEST_NOT_BEFORE = now + min_interval
                return

            if _ACTIVE_REQUESTS >= max_concurrent:
                wait_seconds = max(
                    _NEXT_REQUEST_NOT_BEFORE - now,
                    _REQUEST_SLOT_POLL_INTERVAL_SECONDS,
                )
            else:
                wait_seconds = max(_NEXT_REQUEST_NOT_BEFORE - now, 0.0)

        _sleep(wait_seconds)


def _release_request_slot() -> None:
    global _ACTIVE_REQUESTS

    with _REQUEST_GATE:
        if _ACTIVE_REQUESTS > 0:
            _ACTIVE_REQUESTS -= 1


def _build_config(
    response_mime_type: str | None = None,
    temperature: float | None = None,
) -> Any:
    if SDK_FLAVOR == "google-genai":
        config_kwargs = {}
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if not config_kwargs:
            return None
        return _modern_types.GenerateContentConfig(**config_kwargs)

    generation_config = {}
    if response_mime_type:
        generation_config["response_mime_type"] = response_mime_type
    if temperature is not None:
        generation_config["temperature"] = temperature
    return generation_config or None


def _is_flash3_model(model: str) -> bool:
    normalized = str(model or "").lower()
    return "flash" in normalized and "gemini-3" in normalized


def _is_flash25_model(model: str) -> bool:
    normalized = str(model or "").lower()
    return "flash" in normalized and "gemini-2.5" in normalized


def _is_high_demand_503(exc: Exception) -> bool:
    message = str(exc).lower()
    return "503" in message and "high demand" in message


def _fallback_env_value(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _get_high_demand_fallback_model(model: str, exc: Exception) -> str | None:
    if not _is_high_demand_503(exc):
        return None

    if _is_flash3_model(model):
        fallback = _fallback_env_value(
            "GEMINI_FLASH3_HIGH_DEMAND_FALLBACK_MODEL",
            _FLASH3_HIGH_DEMAND_FALLBACK_MODEL,
        )
    elif _is_flash25_model(model):
        fallback = _fallback_env_value(
            "GEMINI_FLASH25_HIGH_DEMAND_FALLBACK_MODEL",
            _FLASH25_HIGH_DEMAND_FALLBACK_MODEL,
        )
    else:
        return None

    if fallback == model:
        return None
    return fallback


def _generate_modern_content_with_fallbacks(
    *,
    client: Any,
    model: str,
    contents: Any,
    config: Any,
) -> Any:
    attempted_models = {model}
    current_model = model

    while True:
        try:
            return client.models.generate_content(
                model=current_model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            fallback_model = _get_high_demand_fallback_model(current_model, exc)
            if not fallback_model or fallback_model in attempted_models:
                raise
            logger.warning(
                "Gemini model %s returned 503 high demand; retrying with %s.",
                current_model,
                fallback_model,
            )
            attempted_models.add(fallback_model)
            current_model = fallback_model


def _generate_legacy_content_with_fallbacks(
    *,
    model: str,
    contents: Any,
    config: Any,
) -> Any:
    attempted_models = {model}
    current_model = model

    while True:
        model_client = _legacy_genai.GenerativeModel(current_model)
        try:
            if config is None:
                return model_client.generate_content(contents)
            return model_client.generate_content(contents, generation_config=config)
        except Exception as exc:
            fallback_model = _get_high_demand_fallback_model(current_model, exc)
            if not fallback_model or fallback_model in attempted_models:
                raise
            logger.warning(
                "Gemini model %s returned 503 high demand; retrying with %s.",
                current_model,
                fallback_model,
            )
            attempted_models.add(fallback_model)
            current_model = fallback_model


def generate_content(
    *,
    api_key: str,
    model: str,
    contents: Any,
    response_mime_type: str | None = None,
    temperature: float | None = None,
) -> Any:
    _acquire_request_slot()
    try:
        if SDK_FLAVOR == "google-genai":
            client = _modern_genai.Client(
                api_key=api_key,
                http_options=_build_http_options(),
            )
            normalized_contents = _normalize_contents(contents)
            config = _build_config(
                response_mime_type=response_mime_type,
                temperature=temperature,
            )
            return _generate_modern_content_with_fallbacks(
                client=client,
                model=model,
                contents=normalized_contents,
                config=config,
            )

        _legacy_genai.configure(api_key=api_key)
        config = _build_config(
            response_mime_type=response_mime_type,
            temperature=temperature,
        )
        return _generate_legacy_content_with_fallbacks(
            model=model,
            contents=contents,
            config=config,
        )
    finally:
        _release_request_slot()
