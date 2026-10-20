"""Small OpenAI-compatible JSON client with auditable usage accounting."""
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .telemetry import ExecutionLedger


class ModelOutputRetry(Exception):
    """Signal that the model answered with empty or unparsable content."""


class JsonChatClient:
    def __init__(
        self, base_url: str, api_key: str, model: str,
        provider: str = "openai-compatible", timeout: int = 60,
        extra_headers: Optional[Dict[str, str]] = None,
        thinking: str = "", reasoning_effort: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self.thinking = str(thinking or "").strip().lower()
        self.reasoning_effort = str(reasoning_effort or "").strip().lower()

    def _thinking_modes(self) -> List[str]:
        """Attempt order for the thinking switch.

        Reasoning models occasionally answer a schema-bound request with an
        empty content body. Retrying once with reasoning disabled is the
        cheapest recovery that keeps the first attempt's reasoning quality.
        """
        if self.thinking == "disabled":
            return ["disabled"]
        return [self.thinking, "disabled"]

    def complete_json(
        self, role: str, system: str, user: str,
        ledger: Optional[ExecutionLedger] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        last_message = "%s JSON request failed: no attempt made" % self.provider
        for thinking in self._thinking_modes():
            try:
                return self._complete_once(
                    role, system, user, ledger, max_tokens, thinking
                )
            except ModelOutputRetry as exc:
                last_message = str(exc)
        raise RuntimeError(last_message)

    def _complete_once(
        self, role: str, system: str, user: str,
        ledger: Optional[ExecutionLedger], max_tokens: Optional[int],
        thinking: str,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        if thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(self.extra_headers)
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        started = time.monotonic()
        latency = 0
        usage: Dict[str, Any] = {}

        def fail(message: str) -> None:
            if ledger:
                ledger.record_model(
                    role, self.provider, self.model, usage or {},
                    int((time.monotonic() - started) * 1000), False, message,
                )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            message = "%s API returned HTTP %d: %s" % (self.provider, exc.code, detail)
            fail(message)
            raise RuntimeError(message) from None
        except (urllib.error.URLError, socket.timeout, json.JSONDecodeError) as exc:
            message = "%s JSON request failed: %s" % (self.provider, exc)
            fail(message)
            raise RuntimeError(message) from None

        latency = int((time.monotonic() - started) * 1000)
        usage = body.get("usage") or {}
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            message = "%s JSON request failed: %s" % (self.provider, exc)
            fail(message)
            raise RuntimeError(message) from None

        if not str(content or "").strip():
            message = "%s returned empty content (thinking=%s)" % (
                self.provider, thinking or "provider-default",
            )
            fail(message)
            raise ModelOutputRetry(message)

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            message = "%s JSON request failed: %s" % (self.provider, exc)
            fail(message)
            raise ModelOutputRetry(message) from None

        if not isinstance(result, dict):
            message = "%s JSON request failed: model JSON root is not an object" % self.provider
            fail(message)
            raise ModelOutputRetry(message)

        if ledger:
            ledger.record_model(
                role, self.provider, self.model, usage, latency, True,
            )
        return result
