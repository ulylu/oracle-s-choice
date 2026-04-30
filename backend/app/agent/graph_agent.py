from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from ..spoonos_core.graph import StateGraph

from ..divination.tarot import draw_tarot
from ..divination.lenormand import draw_lenormand
from ..divination.liuyao import cast_liuyao
from ..storage.db import Storage
from .lang import detect_language
from .llm_client import LLMClient
from .nodes import detect_intent, fallback_narration, parse_question, rule_route


CHAT_FALLBACK_BY_LANG = {
    "zh": "我在这里听你说。可以多告诉我一些你的感受或发生了什么吗？",
    "en": (
        "I'm here to listen. Could you share a bit more about how you're "
        "feeling or what happened?"
    ),
}


def _narration_max_tokens() -> int:
    """Token budget for narration calls.

    MiMo reasoning models (mimo-v2.5 etc.) tend to spend hundreds of
    tokens on internal ``reasoning_content`` before they emit visible
    ``content``. The default ``LLM_MAX_TOKENS=512`` is enough for the
    parse / route classifiers, but for narration it routinely returns
    ``finish_reason=length`` with empty ``content``. Bumping the budget
    here (configurable via ``LLM_NARRATION_MAX_TOKENS``) lets the model
    finish a real answer.
    """
    raw = os.getenv("LLM_NARRATION_MAX_TOKENS", "2048")
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return min(max(value, 1), 8192)


class WorkflowState(TypedDict, total=False):
    session_id: str
    question: str
    domain: str
    tone: str
    need_clarification: bool
    intent: str
    force_divination: bool
    tool: str
    symbols: List[Dict[str, Any]]
    verdict: str
    advice: List[str]
    message: str
    history: List[Dict[str, Any]]
    trace: List[Dict[str, Any]]
    persisted: bool
    lang: str


TRACE_KEYS = [
    "session_id",
    "question",
    "domain",
    "tone",
    "need_clarification",
    "intent",
    "force_divination",
    "tool",
    "symbols",
    "verdict",
    "advice",
    "message",
    "lang",
]

TRACE_ORDER = ["parse", "route", "divination", "narration", "persist"]


def build_agent(storage: Storage):
    llm_client = LLMClient()

    async def parse_node(state: WorkflowState) -> Dict[str, Any]:
        input_snapshot = _trace_snapshot(state)
        question = state.get("question", "")
        force_divination = bool(state.get("force_divination"))
        lang = detect_language(question)

        fallback = parse_question(question)
        fallback_intent = "divination" if force_divination else detect_intent(question)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a classifier for oracle questions. "
                    "Return JSON only: {\"intent\": \"chat|divination\", "
                    "\"domain\": \"love|career|general\", "
                    "\"tone\": \"gentle|direct\", \"need_clarification\": true|false}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    "Decide intent, domain, tone, and whether more clarification is needed."
                ),
            },
        ]

        payload = await llm_client.chat_json(messages, fallback=fallback)
        intent = payload.get("intent", fallback_intent)
        if force_divination:
            intent = "divination"
        domain = payload.get("domain", fallback.get("domain"))
        tone = payload.get("tone", fallback.get("tone"))
        need_clarification = payload.get(
            "need_clarification", fallback.get("need_clarification")
        )

        output = {
            "intent": intent,
            "domain": domain,
            "tone": tone,
            "need_clarification": bool(need_clarification),
            "lang": lang,
        }
        _attach_llm_meta(output, payload)
        return _with_trace(state, "parse", input_snapshot, output, "ok")

    async def route_node(state: WorkflowState) -> Dict[str, Any]:
        input_snapshot = _trace_snapshot(state)
        intent = state.get("intent", "chat")
        if intent == "chat":
            return _with_trace(state, "route", input_snapshot, {"tool": "chat"}, "ok")
        question = state.get("question", "")
        domain = state.get("domain", "general")
        tone = state.get("tone", "direct")

        fallback_tool = rule_route(question, domain, tone)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an oracle routing engine. "
                    "Select the best divination tool for the question. "
                    "Return JSON only: {\"tool\": \"tarot|lenormand|liuyao\"}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Domain: {domain}\n"
                    f"Tone: {tone}\n"
                    "Choose one tool."
                ),
            },
        ]

        payload = await llm_client.chat_json(messages, fallback={"tool": fallback_tool})
        tool = payload.get("tool") if isinstance(payload, dict) else None
        if tool not in {"tarot", "lenormand", "liuyao"}:
            tool = fallback_tool

        output = {"tool": tool}
        _attach_llm_meta(output, payload)
        return _with_trace(state, "route", input_snapshot, output, "ok")

    async def divination_node(state: WorkflowState) -> Dict[str, Any]:
        input_snapshot = _trace_snapshot(state)
        tool = state.get("tool") or "tarot"
        if tool == "chat":
            return _with_trace(
                state,
                "divination",
                input_snapshot,
                {"symbols": [], "verdict": "", "advice": []},
                "ok",
            )
        question = state.get("question", "")
        session_id = state.get("session_id", "")

        if tool == "tarot":
            result = draw_tarot(question, session_id)
        elif tool == "lenormand":
            result = draw_lenormand(question, session_id)
        else:
            result = cast_liuyao(question, session_id)

        output = {
            "symbols": result.get("symbols", []),
            "verdict": result.get("verdict", ""),
            "advice": result.get("advice", []),
        }
        return _with_trace(state, "divination", input_snapshot, output, "ok")

    async def narration_node(state: WorkflowState) -> Dict[str, Any]:
        input_snapshot = _trace_snapshot(state)
        intent = state.get("intent", "chat")
        tool = state.get("tool", "")
        question = state.get("question", "")
        verdict = state.get("verdict", "")
        advice = state.get("advice", [])
        tone = state.get("tone", "direct")
        need_clarification = state.get("need_clarification", False)
        lang = state.get("lang") or detect_language(question)

        if intent == "chat":
            history = storage.get_recent_messages(state.get("session_id", ""), limit=5)
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a warm, supportive companion. "
                        "Always reply in the SAME language as the user's most recent message: "
                        "Chinese if they write in Chinese, English if they write in English. "
                        "For mixed-language input, follow the dominant language. "
                        "Do NOT translate the user's words back to them; just answer naturally. "
                        "Keep the response concise and match the user's tone. "
                        f"Detected user language for this turn: {lang}."
                    ),
                }
            ]
            for item in history:
                role = item.get("role")
                if role not in {"user", "assistant"}:
                    continue
                messages.append({"role": role, "content": item.get("content", "")})
            messages.append({"role": "user", "content": question})
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an oracle narrator. Compose a concise response that "
                        "explains the divination result and relates it to the question. "
                        "Always reply in the SAME language as the user's question: "
                        "Chinese for Chinese questions, English for English questions, "
                        "dominant language for mixed input. "
                        "Preserve the authentic divination style and meaning regardless of the "
                        "response language. The Verdict and Advice provided below are written in "
                        "Chinese; render their meaning into the response language naturally "
                        "without inventing new symbols. "
                        "Return JSON only: {\"message\": string}. "
                        f"Detected user language for this turn: {lang}."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n"
                        f"Tool: {tool}\n"
                        f"Verdict: {verdict}\n"
                        f"Advice: {advice}\n"
                        f"Tone: {tone}\n"
                        f"Need clarification: {need_clarification}\n"
                        "Explain the result clearly and relate it to the question."
                    ),
                },
            ]

        payload = await llm_client.chat_json(
            messages,
            fallback={},
            max_tokens=_narration_max_tokens(),
        )
        message = payload.get("message") if isinstance(payload, dict) else None
        if not message and isinstance(payload, dict):
            raw = payload.get("_raw")
            if isinstance(raw, str) and raw.strip():
                message = raw.strip()

        narration_fallback_used = False
        if not message:
            narration_fallback_used = True
            if intent == "chat":
                message = CHAT_FALLBACK_BY_LANG.get(lang, CHAT_FALLBACK_BY_LANG["zh"])
            else:
                message = fallback_narration(
                    tool, verdict, advice, tone, need_clarification, lang=lang
                )

        output = {"message": message, "lang": lang}
        _attach_llm_meta(output, payload, success=not narration_fallback_used)
        return _with_trace(state, "narration", input_snapshot, output, "ok")

    async def persist_node(state: WorkflowState) -> Dict[str, Any]:
        input_snapshot = _trace_snapshot(state)
        session_id = state.get("session_id")
        if not session_id:
            return _with_trace(state, "persist", input_snapshot, {"persisted": False}, "ok")

        trace = _normalize_trace(state.get("trace", []))

        storage.upsert_session(session_id)
        storage.add_message(session_id, "user", state.get("question", ""))
        storage.add_message(session_id, "assistant", state.get("message", ""))
        storage.add_reading(
            session_id,
            state.get("tool", ""),
            state.get("symbols", []),
            state.get("verdict", ""),
            state.get("advice", []),
        )
        storage.add_trace(session_id, trace)

        output = _with_trace(state, "persist", input_snapshot, {"persisted": True}, "ok")
        output["trace"] = _normalize_trace(output.get("trace", []))
        return output

    graph = StateGraph(WorkflowState)
    graph.add_node("parse", parse_node)
    graph.add_node("route", route_node)
    graph.add_node("divination", divination_node)
    graph.add_node("narration", narration_node)
    graph.add_node("persist", persist_node)

    graph.add_edge("parse", "route")
    graph.add_edge("route", "divination")
    graph.add_edge("divination", "narration")
    graph.add_edge("narration", "persist")

    graph.set_entry_point("parse")
    return graph.compile()


def _trace_snapshot(state: WorkflowState) -> Dict[str, Any]:
    return {key: copy.deepcopy(state.get(key)) for key in TRACE_KEYS}


def _with_trace(
    state: WorkflowState,
    node: str,
    input_snapshot: Dict[str, Any],
    output: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    trace = list(state.get("trace", []))
    trace.append(
        {
            "node": node,
            "input": input_snapshot,
            "output": copy.deepcopy(output),
            "started_at": _utc_now(),
            "ended_at": _utc_now(),
            "status": status,
        }
    )
    output_with_trace = dict(output)
    output_with_trace["trace"] = trace
    return output_with_trace


def _normalize_trace(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    last_by_node: Dict[str, Dict[str, Any]] = {}
    for item in trace:
        node = item.get("node")
        if node:
            last_by_node[node] = item

    ordered: List[Dict[str, Any]] = []
    for node in TRACE_ORDER:
        if node in last_by_node:
            ordered.append(last_by_node[node])

    return ordered


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attach_llm_meta(output: Dict[str, Any], payload: Any, *, success: bool = True) -> None:
    """Surface llm_provider / fallback_used / llm_debug in node trace output.

    ``llm_provider`` is set ONLY when ``success=True`` AND the LLM client
    returned a non-None ``_provider``. When every attempt failed, or the
    caller is using a rule-based fallback for its primary output, the field
    is intentionally omitted so the trace cannot be misread as a successful
    live response. ``fallback_used`` is always emitted (true or false) so
    the trace has an unambiguous flag. ``llm_debug`` is surfaced when
    present so failures remain inspectable.
    """
    if not isinstance(payload, dict):
        output["fallback_used"] = not success
        return
    debug = payload.get("_debug")
    if debug:
        output["llm_debug"] = debug
    fallback_used = bool(payload.get("_fallback_used")) or not success
    output["fallback_used"] = fallback_used
    if success and not fallback_used:
        provider_used = payload.get("_provider")
        if provider_used:
            output["llm_provider"] = provider_used
