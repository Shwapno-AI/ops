"""Small Qwen client over the OpenAI-compatible chat endpoint (Alibaba Model Studio)."""

from __future__ import annotations

import json
import os
import re
import time

import requests

DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


class QwenError(Exception):
    pass


def extract_json(text: str) -> dict:
    """Accept bare JSON, fenced JSON, or JSON with stray prose around it."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise QwenError("Qwen's reply had no JSON in it") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise QwenError(f"Qwen's JSON was broken: {exc}") from None
    if not isinstance(value, dict):
        raise QwenError("Qwen's reply was not a JSON object")
    return value


class QwenClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL, timeout: int = 180, attempts: int = 4):
        self.api_key = api_key
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.attempts = attempts
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.extra: dict = {"response_format": {"type": "json_object"}}

    @classmethod
    def from_env(cls) -> "QwenClient | None":
        key = (os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
        if not key:
            return None
        return cls(
            key,
            (os.getenv("QWEN_BASE_URL") or "").strip() or DEFAULT_BASE_URL,
            (os.getenv("QWEN_MODEL") or "").strip() or DEFAULT_MODEL,
        )

    def _adapt(self, body: str) -> bool:
        """Some models refuse optional settings; drop or set them and try again."""
        lowered = body.casefold()
        if "enable_thinking" in lowered and "enable_thinking" not in self.extra:
            self.extra["enable_thinking"] = False
            return True
        if "response_format" in lowered and "response_format" in self.extra:
            del self.extra["response_format"]
            return True
        return False

    def chat(self, messages: list[dict]) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        problem = "unknown"
        attempt = 0
        while attempt < self.attempts:
            payload = {"model": self.model, "messages": messages, "temperature": 0, **self.extra}
            try:
                reply = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                problem = f"Network problem: {type(exc).__name__}"
            else:
                if reply.status_code == 200:
                    return self._content(reply)
                body = reply.text[:600]
                problem = f"HTTP {reply.status_code}: {body}"
                if reply.status_code == 400 and self._adapt(body):
                    continue
                if reply.status_code in (401, 403):
                    raise QwenError(
                        "Qwen rejected the API key. Check the key, and check that QWEN_BASE_URL matches "
                        f"the key's region. {problem}"
                    )
                if reply.status_code not in RETRYABLE:
                    raise QwenError(problem)
            attempt += 1
            if attempt < self.attempts:
                time.sleep(min(2**attempt, 30))
        raise QwenError(f"Qwen did not respond after {self.attempts} tries. {problem}")

    def _content(self, reply: requests.Response) -> str:
        try:
            data = reply.json()
            usage = data.get("usage") or {}
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise QwenError(f"Could not understand Qwen's reply: {reply.text[:300]}") from exc
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            raise QwenError("Qwen returned an empty reply")
        return content
