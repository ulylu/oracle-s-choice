from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence


MessageLike = Dict[str, str]

# Maps logical provider name -> required env var that holds the API key.
PROVIDER_KEYS = {
    "mimo": "MIMO_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# Per-provider OpenAI-compatible defaults. The real API key is read from
# PROVIDER_KEYS at call time. base_url should NOT include /chat/completions;
# the suffix is appended in _call_openai_compatible.
PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
    "mimo": {
        "base_url_env": "MIMO_BASE_URL",
        "model_env": "MIMO_MODEL",
        "temperature_env": "MIMO_TEMPERATURE",
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "default_model": "mimo",
    },
    "deepseek": {
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "temperature_env": "DEEPSEEK_TEMPERATURE",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
}

# Preferred provider order. MiMo is tried first when its key is set, so the
# Xiaomi-MiMo key path takes precedence over a real DeepSeek key when both
# are configured. _filter_providers drops any provider whose key is missing.
DEFAULT_PROVIDER_ORDER = ["mimo", "deepseek"]

# Trace debug response bodies are truncated to keep the JSON payload small.
_DEBUG_BODY_LIMIT = 2000


class LLMClient:
    def __init__(self, providers: Optional[List[str]] = None) -> None:
        ordered = providers or DEFAULT_PROVIDER_ORDER
        self.providers = _filter_providers(ordered)

    async def chat_json(
        self,
        messages: Sequence[MessageLike],
        fallback: Optional[Dict[str, Any]] = None,
        *,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Call the first available provider that returns usable text.

        Returns a dict that always includes:
          - ``_provider``: the provider whose call SUCCEEDED, or ``None``
            if every attempt failed and the rule-based fallback is used.
          - ``_debug``: per-attempt diagnostics. The default-safe set is
            ``provider, attempt, endpoint, model, http_status,
            finish_reason, exception, ok``. The full upstream
            ``raw_response_text`` and the model's private
            ``reasoning_content`` are included **only** when
            ``LLM_TRACE_DEBUG=1`` so they can never silently leak into the
            frontend trace UI in normal operation.
          - ``_fallback_used``: ``True`` only when no provider produced a
            usable ``message.content`` value.

        The actual chat payload (e.g. ``{"message": "..."}``) is merged in
        when parsing succeeds; otherwise raw text lives under ``_raw``.

        ``max_tokens`` overrides the ``LLM_MAX_TOKENS`` env default for
        this call only. Narration uses a higher cap because MiMo's
        reasoning models often spend most of the default 512-token budget
        on internal reasoning before they emit ``content``.
        """
        formatted = _to_messages(messages)
        debug_attempts: List[Dict[str, Any]] = []
        last_error: Optional[str] = None
        # Trace-debug mode controls whether the per-attempt entry includes
        # the upstream provider's full raw response body and the model's
        # private reasoning_content. Both can leak sensitive prompt data
        # or internal chain-of-thought into the frontend trace UI, so they
        # default to off and require LLM_TRACE_DEBUG=1 to opt in.
        expose_debug = _trace_debug_enabled()

        for provider in self.providers:
            for attempt_idx in range(_get_retries()):
                attempt: Dict[str, Any] = {
                    "provider": provider,
                    "attempt": attempt_idx + 1,
                    "endpoint": None,
                    "model": None,
                    "http_status": None,
                    "finish_reason": None,
                    "exception": None,
                    "ok": False,
                }
                if expose_debug:
                    attempt["raw_response_text"] = None
                    attempt["reasoning_content"] = None
                try:
                    content_text, info = await asyncio.to_thread(
                        _call_openai_compatible,
                        provider,
                        formatted,
                        max_tokens,
                    )
                    attempt.update(
                        endpoint=info["endpoint"],
                        model=info["model"],
                        http_status=info["http_status"],
                        finish_reason=info.get("finish_reason"),
                        ok=True,
                    )
                    if expose_debug:
                        attempt["raw_response_text"] = _truncate(info["raw_response_text"])
                        attempt["reasoning_content"] = info.get("reasoning_content")
                    debug_attempts.append(attempt)

                    payload = _parse_json_payload(content_text)
                    if not isinstance(payload, dict):
                        payload = {"_raw": content_text}
                    payload["_provider"] = provider
                    payload["_raw"] = content_text
                    payload["_debug"] = debug_attempts
                    payload["_fallback_used"] = False
                    return payload
                except _LLMHTTPError as exc:
                    attempt.update(
                        endpoint=exc.endpoint,
                        model=exc.model,
                        http_status=exc.http_status,
                        finish_reason=exc.finish_reason,
                        exception=str(exc),
                    )
                    if expose_debug:
                        attempt["raw_response_text"] = _truncate(exc.raw_response_text)
                        if exc.reasoning_content is not None:
                            attempt["reasoning_content"] = _truncate(exc.reasoning_content)
                    debug_attempts.append(attempt)
                    last_error = str(exc)
                except Exception as exc:  # noqa: BLE001 - surfaced via trace
                    attempt["exception"] = str(exc)
                    debug_attempts.append(attempt)
                    last_error = str(exc)

        result: Dict[str, Any] = dict(fallback or {})
        result["_provider"] = None
        result["_fallback_used"] = True
        result["_debug"] = debug_attempts
        if last_error is not None:
            result["_error"] = last_error
        return result


class _LLMHTTPError(RuntimeError):
    """HTTP / transport / shape failure carrying enough info for the trace."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: Optional[str],
        model: Optional[str],
        http_status: Optional[int],
        raw_response_text: Optional[str],
        finish_reason: Optional[str] = None,
        reasoning_content: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.model = model
        self.http_status = http_status
        self.raw_response_text = raw_response_text
        # finish_reason / reasoning_content carry context for "empty content"
        # failures so the trace can show whether MiMo simply ran out of
        # tokens on internal reasoning vs hit a real shape error.
        self.finish_reason = finish_reason
        self.reasoning_content = reasoning_content


def _call_openai_compatible(
    provider: str,
    messages: List[Dict[str, str]],
    max_tokens_override: Optional[int] = None,
) -> tuple[str, Dict[str, Any]]:
    """Send an OpenAI-style chat completion. Returns (content, debug_info).

    The returned text is **always** ``choices[0].message.content`` — never
    ``reasoning_content``. ``reasoning_content`` is the model's private
    chain-of-thought scratch space (MiMo / DeepSeek-R1 / etc.) and must not
    be shown to the user. If the provider returns empty ``content`` (with
    or without ``reasoning_content``), or if it stopped with
    ``finish_reason="length"`` before producing real content, this is
    treated as a provider failure so ``chat_json`` can try the next
    provider or fall through to the rule-based fallback.

    ``max_tokens_override`` lets callers (e.g. narration) request a larger
    output budget than ``LLM_MAX_TOKENS`` for this call only.
    """
    cfg = _provider_config(provider)
    api_key = os.getenv(PROVIDER_KEYS[provider], "").strip()
    if not api_key:
        raise _LLMHTTPError(
            f"{PROVIDER_KEYS[provider]} is not set for provider '{provider}'",
            endpoint=None,
            model=None,
            http_status=None,
            raw_response_text=None,
        )

    base_url = (os.getenv(cfg["base_url_env"], "") or cfg["default_base_url"]).rstrip("/")
    endpoint = base_url + "/chat/completions"
    model = os.getenv(cfg["model_env"], "") or cfg["default_model"]
    temperature = _get_float_env(cfg["temperature_env"], 0.7)
    max_tokens = _clamp_max_tokens(max_tokens_override) if max_tokens_override else _get_max_tokens()

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    raw_response_text: Optional[str] = None
    http_status: Optional[int] = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            http_status = getattr(response, "status", None) or response.getcode()
            raw_response_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        try:
            raw_response_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw_response_text = "<unreadable error body>"
        raise _LLMHTTPError(
            f"{provider} HTTP {http_status}: {_truncate(raw_response_text, 800)}",
            endpoint=endpoint,
            model=model,
            http_status=http_status,
            raw_response_text=raw_response_text,
        ) from exc
    except urllib.error.URLError as exc:
        raise _LLMHTTPError(
            f"{provider} URL error: {exc.reason}",
            endpoint=endpoint,
            model=model,
            http_status=None,
            raw_response_text=None,
        ) from exc

    try:
        data = json.loads(raw_response_text) if raw_response_text else {}
    except json.JSONDecodeError as exc:
        raise _LLMHTTPError(
            f"{provider} returned non-JSON body",
            endpoint=endpoint,
            model=model,
            http_status=http_status,
            raw_response_text=raw_response_text,
        ) from exc

    choices = data.get("choices") or []
    if not choices:
        raise _LLMHTTPError(
            f"{provider} response has no choices",
            endpoint=endpoint,
            model=model,
            http_status=http_status,
            raw_response_text=raw_response_text,
        )

    choice = choices[0]
    message = choice.get("message") or {}
    finish_reason = choice.get("finish_reason")
    content = (message.get("content") or "").strip()
    reasoning_content = (message.get("reasoning_content") or "").strip()

    if not content:
        # Empty content is a provider failure even when reasoning_content
        # has text. reasoning_content is the model's private scratch pad
        # ("First, the user's question is in Chinese..."); leaking it to
        # the user as an answer would be wrong. The most common cause is
        # finish_reason="length" — MiMo burned the whole max_tokens budget
        # on internal reasoning and never emitted a real answer. The fix
        # is either a larger max_tokens budget for this call or a simpler
        # prompt; both happen upstream in the caller.
        raise _LLMHTTPError(
            (
                f"{provider} returned empty content "
                f"(finish_reason={finish_reason!r}, "
                f"reasoning_content_len={len(reasoning_content)})"
            ),
            endpoint=endpoint,
            model=model,
            http_status=http_status,
            raw_response_text=raw_response_text,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content or None,
        )

    if finish_reason == "length":
        # We have *some* content but the model was cut off mid-answer.
        # Mark this as a soft failure so chat_json can retry / fall back;
        # truncated JSON is unsafe to feed back into _parse_json_payload.
        raise _LLMHTTPError(
            f"{provider} stopped with finish_reason=length (truncated content)",
            endpoint=endpoint,
            model=model,
            http_status=http_status,
            raw_response_text=raw_response_text,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content or None,
        )

    info = {
        "endpoint": endpoint,
        "model": model,
        "http_status": http_status,
        "raw_response_text": raw_response_text,
        "content": content,
        "reasoning_content": reasoning_content or None,
        "finish_reason": finish_reason,
    }
    return content, info


def _provider_config(provider: str) -> Dict[str, str]:
    cfg = PROVIDER_DEFAULTS.get(provider)
    if not cfg:
        raise RuntimeError(f"Unknown provider '{provider}'")
    return cfg


def _parse_json_payload(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
        return {"message": str(payload)}
    except json.JSONDecodeError:
        return {"_raw": raw}


def _to_messages(messages: Sequence[MessageLike]) -> List[Dict[str, str]]:
    formatted: List[Dict[str, str]] = []
    for item in messages:
        role = item.get("role", "user") or "user"
        content = item.get("content", "") or ""
        formatted.append({"role": role, "content": content})
    return formatted


def _filter_providers(providers: Sequence[str]) -> List[str]:
    enabled: List[str] = []
    for provider in providers:
        env_name = PROVIDER_KEYS.get(provider)
        if env_name and os.getenv(env_name):
            enabled.append(provider)
    return enabled


def _get_retries() -> int:
    raw = os.getenv("LLM_RETRIES", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _get_max_tokens() -> int:
    raw = os.getenv("LLM_MAX_TOKENS", "512")
    try:
        value = int(raw)
    except ValueError:
        return 512
    return _clamp_max_tokens(value)


def _clamp_max_tokens(value: Optional[int]) -> int:
    if value is None:
        return _get_max_tokens()
    return min(max(int(value), 1), 8192)


def _trace_debug_enabled() -> bool:
    """Return True when LLM_TRACE_DEBUG=1 (or true/yes/on).

    Gates exposure of ``reasoning_content`` in the trace. Off by default
    so the agent's private chain-of-thought never leaks into normal
    /chat responses.
    """
    raw = (os.getenv("LLM_TRACE_DEBUG", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _truncate(text: Optional[str], limit: int = _DEBUG_BODY_LIMIT) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"
