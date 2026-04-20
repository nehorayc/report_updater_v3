from __future__ import annotations

import base64
import inspect
import os
import time
from dataclasses import dataclass
from typing import Any, Dict

import gemini_client
from llm_usage import record_usage


_DEFAULT_PROVIDER = "gemini"
_DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
_DEFAULT_OPENAI_REASONING_EFFORT = "low"

_OPENAI_ROLE_ENV = {
    "writer": "OPENAI_WRITER_MODEL",
    "analyzer": "OPENAI_ANALYZER_MODEL",
    "vision": "OPENAI_VISION_MODEL",
    "research_ranker": "OPENAI_RESEARCH_RANKER_MODEL",
    "research_fallback": "OPENAI_RESEARCH_RANKER_MODEL",
    "translator": "OPENAI_TRANSLATOR_MODEL",
    "graph": "OPENAI_GRAPH_MODEL",
    "chapter_judge": "OPENAI_CHAPTER_JUDGE_MODEL",
}


@dataclass
class LLMResponse:
    text: str
    raw_response: Any
    provider: str
    model: str


def get_provider() -> str:
    provider = str(os.getenv("LLM_PROVIDER", _DEFAULT_PROVIDER) or _DEFAULT_PROVIDER).strip().lower()
    if provider not in {"gemini", "openai"}:
        return _DEFAULT_PROVIDER
    return provider


def provider_display_name(provider: str | None = None) -> str:
    provider = provider or get_provider()
    return "OpenAI" if provider == "openai" else "Gemini"


def required_api_key_env(provider: str | None = None) -> str:
    return "OPENAI_API_KEY" if (provider or get_provider()) == "openai" else "GEMINI_API_KEY"


def get_api_key(provider: str | None = None) -> str:
    return str(os.getenv(required_api_key_env(provider), "") or "").strip()


def missing_api_key_error(provider: str | None = None) -> str:
    env_name = required_api_key_env(provider)
    return f"{env_name} not found"


def resolve_model(gemini_model: str, *, role: str | None = None, provider: str | None = None) -> str:
    provider = provider or get_provider()
    if provider == "openai":
        if role:
            role_env = _OPENAI_ROLE_ENV.get(role)
            if role_env:
                configured = str(os.getenv(role_env, "") or "").strip()
                if configured:
                    return configured
        return str(os.getenv("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL) or _DEFAULT_OPENAI_MODEL).strip()
    return str(gemini_model or "").strip()


def selected_provider_model() -> str:
    if get_provider() == "openai":
        return resolve_model("", provider="openai")
    return "configured Gemini defaults"


def _operation_from_stack() -> str:
    for frame_info in inspect.stack()[2:8]:
        module = inspect.getmodule(frame_info.frame)
        module_name = getattr(module, "__name__", "")
        if module_name and module_name not in {"llm_client", "gemini_client"}:
            return f"{module_name}.{frame_info.function}"
    return "llm.generate_content"


def _attr_or_key(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_gemini_usage(response: Any) -> Dict[str, int | None]:
    usage = _attr_or_key(response, "usage_metadata")
    input_tokens = _attr_or_key(usage, "prompt_token_count")
    output_tokens = _attr_or_key(usage, "candidates_token_count")
    total_tokens = _attr_or_key(usage, "total_token_count")
    cached_tokens = _attr_or_key(usage, "cached_content_token_count")
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _extract_openai_usage(response: Any) -> Dict[str, int | None]:
    usage = _attr_or_key(response, "usage")
    details = _attr_or_key(usage, "input_tokens_details")
    return {
        "input_tokens": _attr_or_key(usage, "input_tokens"),
        "cached_input_tokens": _attr_or_key(details, "cached_tokens"),
        "output_tokens": _attr_or_key(usage, "output_tokens"),
        "total_tokens": _attr_or_key(usage, "total_tokens"),
    }


def _coerce_openai_text(response: Any) -> str:
    output_text = _attr_or_key(response, "output_text")
    if output_text is not None:
        return str(output_text)

    output = _attr_or_key(response, "output", [])
    chunks = []
    for item in output or []:
        for content in _attr_or_key(item, "content", []) or []:
            text = _attr_or_key(content, "text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def _contents_to_openai_input(contents: Any) -> Any:
    if isinstance(contents, str):
        return contents

    if not isinstance(contents, list):
        return str(contents)

    parts = []
    for item in contents:
        if isinstance(item, dict) and {"mime_type", "data"}.issubset(item.keys()):
            raw_data = item.get("data") or b""
            if isinstance(raw_data, str):
                raw_data = raw_data.encode("utf-8")
            encoded = base64.b64encode(raw_data).decode("ascii")
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{item.get('mime_type')};base64,{encoded}",
                }
            )
        else:
            parts.append({"type": "input_text", "text": str(item)})

    return [{"role": "user", "content": parts}]


def _generate_openai_content(
    *,
    api_key: str,
    model: str,
    contents: Any,
    response_mime_type: str | None = None,
    temperature: float | None = None,
) -> LLMResponse:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("The openai package is required when LLM_PROVIDER=openai.") from exc

    client = OpenAI(api_key=api_key)
    request_kwargs: Dict[str, Any] = {
        "model": model,
        "input": _contents_to_openai_input(contents),
        "reasoning": {
            "effort": str(
                os.getenv("OPENAI_REASONING_EFFORT", _DEFAULT_OPENAI_REASONING_EFFORT)
                or _DEFAULT_OPENAI_REASONING_EFFORT
            ).strip()
        },
    }
    if temperature is not None:
        request_kwargs["temperature"] = temperature
    if response_mime_type == "application/json":
        request_kwargs["text"] = {"format": {"type": "json_object"}}

    response = client.responses.create(**request_kwargs)
    actual_model = str(_attr_or_key(response, "model", model) or model)
    return LLMResponse(
        text=_coerce_openai_text(response),
        raw_response=response,
        provider="openai",
        model=actual_model,
    )


def _response_usage(provider: str, response: Any) -> Dict[str, int | None]:
    if provider == "openai":
        raw = _attr_or_key(response, "raw_response", response)
        return _extract_openai_usage(raw)
    return _extract_gemini_usage(response)


def generate_content(
    *,
    api_key: str,
    model: str,
    contents: Any,
    response_mime_type: str | None = None,
    temperature: float | None = None,
    operation: str | None = None,
) -> Any:
    provider = get_provider()
    operation_name = operation or _operation_from_stack()
    start = time.time()
    try:
        if provider == "openai":
            response = _generate_openai_content(
                api_key=api_key,
                model=model,
                contents=contents,
                response_mime_type=response_mime_type,
                temperature=temperature,
            )
            actual_model = response.model
        else:
            response = gemini_client.generate_content(
                api_key=api_key,
                model=model,
                contents=contents,
                response_mime_type=response_mime_type,
                temperature=temperature,
            )
            actual_model = str(
                _attr_or_key(response, "model_version")
                or _attr_or_key(response, "model")
                or model
            )

        usage = _response_usage(provider, response)
        record_usage(
            provider=provider,
            model=actual_model,
            operation=operation_name,
            success=True,
            latency_seconds=time.time() - start,
            **usage,
        )
        return response
    except Exception as exc:
        record_usage(
            provider=provider,
            model=model,
            operation=operation_name,
            success=False,
            latency_seconds=time.time() - start,
            error=str(exc),
        )
        raise
