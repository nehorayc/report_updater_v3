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


def generate_content(
    *,
    api_key: str,
    model: str,
    contents: Any,
    response_mime_type: str | None = None,
    temperature: float | None = None,
) -> Any:
    if SDK_FLAVOR == "google-genai":
        client = _modern_genai.Client(api_key=api_key)
        return client.models.generate_content(
            model=model,
            contents=_normalize_contents(contents),
            config=_build_config(
                response_mime_type=response_mime_type,
                temperature=temperature,
            ),
        )

    _legacy_genai.configure(api_key=api_key)
    model_client = _legacy_genai.GenerativeModel(model)
    config = _build_config(
        response_mime_type=response_mime_type,
        temperature=temperature,
    )
    if config is None:
        return model_client.generate_content(contents)
    return model_client.generate_content(contents, generation_config=config)

