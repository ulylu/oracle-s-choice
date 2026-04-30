from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent.graph_agent import build_agent
from .agent.llm_client import DEFAULT_PROVIDER_ORDER, _filter_providers, PROVIDER_KEYS
from .storage.db import Storage


load_dotenv(override=True)

_enabled_providers = _filter_providers(DEFAULT_PROVIDER_ORDER)
_key_status = {
    name: "SET" if os.getenv(env_key) else "MISSING"
    for name, env_key in PROVIDER_KEYS.items()
}
print(f"LLM providers enabled: {_enabled_providers}")
print(f"LLM key status: {_key_status}")

app = FastAPI(title="Oracle's Choice", version="0.1.0")

# CORS: default allowlist covers local dev (localhost / 127.0.0.1 on any
# port) and any Vercel preview / production domain. Override at deploy
# time by setting CORS_ORIGIN_REGEX to a different Python regex (e.g.
# r"^https://(oracle\.example\.com|.*\.vercel\.app)$"). allow_credentials
# is False because no cookies are used; this also keeps the regex valid
# under the CORS spec.
_DEFAULT_CORS_ORIGIN_REGEX = (
    r"^(https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https://([a-z0-9-]+\.)*vercel\.app)$"
)
_CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or _DEFAULT_CORS_ORIGIN_REGEX

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_CORS_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> Dict[str, str]:
    return {"status": "ok", "service": "oracle-choice-backend"}

storage = Storage()
agent = build_agent(storage)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    force_divination: bool | None = None


class ChatResponse(BaseModel):
    session_id: str
    message: str
    tool: str
    trace: List[Dict[str, Any]]
    reading: Dict[str, Any]


TRACE_ORDER = ["parse", "route", "divination", "narration", "persist"]


def _normalize_trace(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    last_by_node: Dict[str, Dict[str, Any]] = {}
    for item in trace:
        node = item.get("node")
        if node:
            last_by_node[node] = item
    return [last_by_node[node] for node in TRACE_ORDER if node in last_by_node]


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    session_id = payload.session_id or str(uuid4())
    context = await agent.invoke(
        {
            "session_id": session_id,
            "question": payload.message,
            "force_divination": bool(payload.force_divination),
        }
    )

    reading = {
        "symbols": context.get("symbols", []),
        "verdict": context.get("verdict", ""),
        "advice": context.get("advice", []),
    }

    return ChatResponse(
        session_id=session_id,
        message=context.get("message", ""),
        tool=context.get("tool", ""),
        trace=_normalize_trace(context.get("trace", [])),
        reading=reading,
    )
