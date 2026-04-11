from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import gemini_client


def test_generate_content_uses_retrying_http_options_by_default(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return "ok"

    class FakeClient:
        def __init__(self, *, api_key, http_options=None, **kwargs):
            captured["api_key"] = api_key
            captured["http_options"] = http_options
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client, "SDK_FLAVOR", "google-genai")
    monkeypatch.setattr(gemini_client, "_modern_genai", SimpleNamespace(Client=FakeClient))

    response = gemini_client.generate_content(
        api_key="test-key",
        model="gemini-2.5-flash",
        contents="hello",
    )

    retry_options = captured["http_options"].retry_options
    assert response == "ok"
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gemini-2.5-flash"
    assert retry_options.attempts == 4
    assert retry_options.initial_delay == 1.0
    assert retry_options.max_delay == 20.0
    assert retry_options.exp_base == 2.0
    assert retry_options.jitter == 1.0
    assert 503 in retry_options.http_status_codes


def test_generate_content_respects_retry_env_overrides(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            return "ok"

    class FakeClient:
        def __init__(self, *, api_key, http_options=None, **kwargs):
            captured["http_options"] = http_options
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client, "SDK_FLAVOR", "google-genai")
    monkeypatch.setattr(gemini_client, "_modern_genai", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("GEMINI_RETRY_ATTEMPTS", "6")
    monkeypatch.setenv("GEMINI_RETRY_INITIAL_DELAY_SECONDS", "2.5")
    monkeypatch.setenv("GEMINI_RETRY_MAX_DELAY_SECONDS", "30")
    monkeypatch.setenv("GEMINI_RETRY_EXP_BASE", "3")
    monkeypatch.setenv("GEMINI_RETRY_JITTER", "0.25")

    gemini_client.generate_content(
        api_key="test-key",
        model="gemini-2.5-flash",
        contents="hello",
    )

    retry_options = captured["http_options"].retry_options
    assert retry_options.attempts == 6
    assert retry_options.initial_delay == 2.5
    assert retry_options.max_delay == 30.0
    assert retry_options.exp_base == 3.0
    assert retry_options.jitter == 0.25


def test_generate_content_can_disable_retries(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            return "ok"

    class FakeClient:
        def __init__(self, *, api_key, http_options=None, **kwargs):
            captured["http_options"] = http_options
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client, "SDK_FLAVOR", "google-genai")
    monkeypatch.setattr(gemini_client, "_modern_genai", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("GEMINI_RETRY_ATTEMPTS", "1")

    gemini_client.generate_content(
        api_key="test-key",
        model="gemini-2.5-flash",
        contents="hello",
    )

    assert captured["http_options"] is None


def test_generate_content_serializes_requests_when_max_concurrency_is_one(monkeypatch):
    active = {"count": 0, "max": 0}
    lock = threading.Lock()

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.05)
            with lock:
                active["count"] -= 1
            return "ok"

    class FakeClient:
        def __init__(self, *, api_key, http_options=None, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client, "SDK_FLAVOR", "google-genai")
    monkeypatch.setattr(gemini_client, "_modern_genai", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("GEMINI_MAX_CONCURRENT_REQUESTS", "1")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(gemini_client, "_ACTIVE_REQUESTS", 0)
    monkeypatch.setattr(gemini_client, "_NEXT_REQUEST_NOT_BEFORE", 0.0)

    barrier = threading.Barrier(3)

    def worker() -> None:
        barrier.wait()
        gemini_client.generate_content(
            api_key="test-key",
            model="gemini-2.5-flash",
            contents="hello",
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()

    barrier.wait()

    for thread in threads:
        thread.join(timeout=1.0)
        assert not thread.is_alive()

    assert active["max"] == 1


def test_generate_content_enforces_min_interval_between_requests(monkeypatch):
    call_times: list[float] = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            call_times.append(time.monotonic())
            return "ok"

    class FakeClient:
        def __init__(self, *, api_key, http_options=None, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client, "SDK_FLAVOR", "google-genai")
    monkeypatch.setattr(gemini_client, "_modern_genai", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("GEMINI_MAX_CONCURRENT_REQUESTS", "1")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0.12")
    monkeypatch.setattr(gemini_client, "_ACTIVE_REQUESTS", 0)
    monkeypatch.setattr(gemini_client, "_NEXT_REQUEST_NOT_BEFORE", 0.0)

    gemini_client.generate_content(
        api_key="test-key",
        model="gemini-2.5-flash",
        contents="hello",
    )
    gemini_client.generate_content(
        api_key="test-key",
        model="gemini-2.5-flash",
        contents="hello again",
    )

    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.1
