"""OpenAI-compatible CLIProxyAPI client used by BuildMarshalAI.

The adapter intentionally accepts the message format previously consumed by
Qwen2.5-VL (``{"type": "image", "image": "/path/page.png"}``) so chat,
document generation, Gmail drafting, and Calendar interpretation can keep
calling the existing ``vl_generate`` interface.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests


class CLIProxyError(RuntimeError):
    """Raised when CLIProxyAPI is unavailable or returns an invalid response."""


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class CLIProxyClient:
    """Small synchronous client for CLIProxyAPI's OpenAI-compatible surface."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        preferred_model: str | None = None,
        timeout_seconds: int | None = None,
        verify_ssl: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("CLIPROXY_BASE_URL") or "http://127.0.0.1:8317/v1").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("CLIPROXY_API_KEY", "")
        self.preferred_model = preferred_model or os.getenv("CLIPROXY_MODEL", "gemini-3.7-flash")
        self.timeout_seconds = timeout_seconds or int(os.getenv("CLIPROXY_TIMEOUT_SECONDS", "240"))
        self.verify_ssl = _as_bool(os.getenv("CLIPROXY_VERIFY_SSL"), True) if verify_ssl is None else verify_ssl
        self.session = session or requests.Session()
        self._selected_model: str | None = None

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        request_timeout: int | tuple[int, int] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.request(
                method,
                url,
                headers=self.headers,
                timeout=request_timeout or self.timeout_seconds,
                verify=self.verify_ssl,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CLIProxyError(
                f"Cannot reach CLIProxyAPI at {self.base_url}. Start the proxy and check "
                "CLIPROXY_BASE_URL. A Kaggle notebook cannot use your PC's 127.0.0.1."
            ) from exc
        if not response.ok:
            detail = response.text.strip()[:1000]
            raise CLIProxyError(f"CLIProxyAPI returned HTTP {response.status_code}: {detail}")
        return response

    def list_models(self, request_timeout: int | tuple[int, int] | None = None) -> list[str]:
        payload = self._request("GET", "models", request_timeout=request_timeout).json()
        models = payload.get("data", []) if isinstance(payload, Mapping) else []
        return [str(item["id"]) for item in models if isinstance(item, Mapping) and item.get("id")]

    def select_model(self, requested: str | None = None, refresh: bool = False) -> str:
        """Select an exposed Antigravity model without trusting a stale alias.

        Frontend values left over from the old Qwen setup are intentionally
        ignored. If the preferred identifier is absent, the newest exposed
        Gemini Flash identifier is selected from ``/v1/models``.
        """
        if self._selected_model and not refresh and not requested:
            return self._selected_model

        requested = (requested or "").strip()
        if "qwen" in requested.lower():
            requested = ""
        models = self.list_models()
        if not models:
            raise CLIProxyError("CLIProxyAPI returned no models. Complete Antigravity OAuth login first.")

        preferred = requested or self.preferred_model
        if preferred in models:
            self._selected_model = preferred
            return preferred

        flash_models = [model for model in models if "gemini" in model.lower() and "flash" in model.lower()]
        if flash_models:
            self._selected_model = sorted(flash_models, reverse=True)[0]
            return self._selected_model

        raise CLIProxyError(
            f"Requested model '{preferred}' is unavailable and no Gemini Flash model was exposed. "
            f"Available models: {', '.join(models[:30])}"
        )

    @staticmethod
    def image_data_url(value: str | os.PathLike[str]) -> str:
        raw_value = str(value)
        if raw_value.startswith(("data:", "http://", "https://")):
            return raw_value
        path = Path(raw_value)
        if not path.is_file():
            raise CLIProxyError(f"Image does not exist: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def convert_messages(self, messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if not isinstance(content, list):
                converted.append({"role": role, "content": str(content)})
                continue

            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, Mapping):
                    parts.append({"type": "text", "text": str(part)})
                    continue
                part_type = str(part.get("type", "text"))
                if part_type in {"image", "image_url"}:
                    image_value: Any = part.get("image")
                    if image_value is None:
                        image_value = part.get("image_url")
                    if isinstance(image_value, Mapping):
                        image_value = image_value.get("url")
                    if image_value:
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": self.image_data_url(str(image_value))},
                        })
                else:
                    parts.append({"type": "text", "text": str(part.get("text", ""))})
            converted.append({"role": role, "content": parts})
        return converted

    @staticmethod
    def _extract_text(payload: Mapping[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CLIProxyError(f"Unexpected CLIProxyAPI response: {str(payload)[:1000]}") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, Mapping) and item.get("text")
            )
        return str(content)

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> tuple[str, str]:
        selected_model = self.select_model(model)
        response = self._request(
            "POST",
            "chat/completions",
            json={
                "model": selected_model,
                "messages": self.convert_messages(messages),
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": False,
            },
        )
        return self._extract_text(response.json()), selected_model

    def status(self) -> dict[str, Any]:
        try:
            models = self.list_models(request_timeout=(3, 10))
            selected = self.select_model()
            return {
                "connected": True,
                "base_url": self.base_url,
                "selected_model": selected,
                "model_count": len(models),
            }
        except Exception as exc:
            return {
                "connected": False,
                "base_url": self.base_url,
                "selected_model": None,
                "error": str(exc),
            }
