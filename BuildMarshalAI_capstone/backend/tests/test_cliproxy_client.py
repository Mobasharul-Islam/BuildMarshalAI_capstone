import base64
from pathlib import Path

import pytest

from backend.cliproxy_client import CLIProxyClient, CLIProxyError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_selects_requested_model_from_proxy_catalog():
    session = FakeSession([FakeResponse({"data": [{"id": "gemini-3.7-flash"}]})])
    client = CLIProxyClient(api_key="local-key", session=session)
    assert client.select_model() == "gemini-3.7-flash"
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer local-key"


def test_stale_qwen_frontend_model_falls_back_to_flash():
    session = FakeSession([FakeResponse({"data": [{"id": "gemini-3-flash"}, {"id": "claude-x"}]})])
    client = CLIProxyClient(session=session)
    assert client.select_model("qwen2.5-vl") == "gemini-3-flash"


def test_converts_qwen_image_part_to_openai_image_url(tmp_path: Path):
    image = tmp_path / "page.png"
    image.write_bytes(b"not-a-real-png")
    client = CLIProxyClient(session=FakeSession([]))
    converted = client.convert_messages([
        {"role": "user", "content": [
            {"type": "image", "image": str(image)},
            {"type": "text", "text": "Read this page"},
        ]}
    ])
    url = converted[0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"not-a-real-png"


def test_chat_uses_non_streaming_openai_endpoint():
    session = FakeSession([
        FakeResponse({"data": [{"id": "gemini-3.7-flash"}]}),
        FakeResponse({"choices": [{"message": {"content": "Answer"}}]}),
    ])
    client = CLIProxyClient(session=session)
    text, model = client.chat([{"role": "user", "content": "Hello"}])
    assert (text, model) == ("Answer", "gemini-3.7-flash")
    method, url, kwargs = session.calls[1]
    assert method == "POST"
    assert url.endswith("/v1/chat/completions")
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["max_tokens"] == 4096


def test_missing_flash_model_has_actionable_error():
    session = FakeSession([FakeResponse({"data": [{"id": "claude-only"}]})])
    client = CLIProxyClient(session=session)
    with pytest.raises(CLIProxyError, match="no Gemini Flash"):
        client.select_model()
