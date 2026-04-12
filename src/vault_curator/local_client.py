"""로컬 OpenAI-호환 엔드포인트 호출기."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request


class LocalModelError(RuntimeError):
    """로컬 모델 호출 실패."""


@dataclass
class LocalModelConfig:
    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.2
    timeout_seconds: int = 180
    max_output_tokens: int | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def _extract_message_text(content: object) -> str | None:
    if isinstance(content, str):
        return content

    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text
        nested_content = content.get("content")
        if isinstance(nested_content, str) and nested_content.strip():
            return nested_content
        return None

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
                continue

            nested_content = item.get("content")
            if isinstance(nested_content, str) and nested_content:
                text_parts.append(nested_content)

        merged = "".join(text_parts).strip()
        return merged or None

    return None


def generate_json(prompt: str, cfg: LocalModelConfig) -> str:
    """OpenAI-호환 chat completions 엔드포인트에 프롬프트를 보낸다."""
    payload = {
        "model": cfg.model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": cfg.temperature,
        "response_format": {"type": "json_object"},
    }
    if cfg.max_output_tokens is not None:
        payload["max_tokens"] = cfg.max_output_tokens

    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    req = request.Request(
        cfg.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LocalModelError(
            f"HTTP {exc.code} while calling local model: {detail}"
        ) from exc
    except error.URLError as exc:
        raise LocalModelError(
            f"Could not reach local model endpoint: {cfg.endpoint}"
        ) from exc
    except TimeoutError as exc:
        raise LocalModelError(
            f"Timed out while calling local model: {cfg.endpoint}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalModelError(
            "Local model response was not valid JSON."
        ) from exc

    choices = data.get("choices") or []
    if not choices:
        raise LocalModelError("Local model response did not contain choices.")

    message = choices[0].get("message") or {}
    content = message.get("content", "")
    extracted = _extract_message_text(content)
    if extracted is not None:
        return extracted

    message_keys = sorted(message.keys())
    finish_reason = choices[0].get("finish_reason")
    if finish_reason == "length" and message.get("reasoning_content"):
        raise LocalModelError(
            "Local model exhausted output tokens before producing content. "
            "Increase max_output_tokens for this stage."
        )
    raise LocalModelError(
        "Local model response content format was unsupported: "
        f"type={type(content).__name__}, message_keys={message_keys}, "
        f"finish_reason={finish_reason}"
    )
