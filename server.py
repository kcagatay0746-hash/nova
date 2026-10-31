"""Nova — Türkçe, araç kullanabilen sesli yapay zekâ asistanı (backend).

Uç noktalar:
    POST /api/ask            eski istemcilerle uyumlu tek yanıt
    POST /api/chat/stream    SSE ile akan yanıt (tarayıcı)
    GET  /api/chat/stream    SSE ile akan yanıt (EventSource)
    POST /api/review         kod incelemesi
    POST /api/site-check     site kontrolü + isteğe bağlı analiz
    GET  /api/memory         kalıcı notları listele
    POST /api/memory         not ekle
    DELETE /api/memory       not/geçmiş temizle
    GET  /api/tools          ajan araçlarının şeması
    GET  /api/health         sağlık + sağlayıcı bilgisi

Çalıştırma:  uvicorn server:app --host 0.0.0.0 --port 5000
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nova.agent import NovaAgent
from nova.config import Settings
from nova.llm import ProviderError, build_provider
from nova.memory import MemoryStore
from nova.prompts import CODE_REVIEW_PROMPT
from nova.safety import RateLimiter, SafetyError, clean_text
from nova.tools import ToolContext, ToolError, build_tools

logger = logging.getLogger("nova")

settings = Settings.from_env()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

memory = MemoryStore(settings.memory_db)
provider = build_provider(settings)
agent = NovaAgent(provider=provider, memory=memory, settings=settings)
limiter = RateLimiter(settings.rate_limit_per_minute, 60.0)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Nova hazır — sağlayıcı=%s model=%s hafıza=%s",
        provider.name,
        provider.model,
        settings.memory_db,
    )
    yield


app = FastAPI(title="Nova", version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client = request.client.host if request.client else "anonim"
        if not limiter.allow(client):
            return JSONResponse(
                status_code=429,
                content={"error": "Çok sık istek gönderildi. Biraz bekleyip tekrar dene."},
                headers={"Retry-After": str(limiter.retry_after(client))},
            )
    return await call_next(request)


# ============================================================ şemalar

class AskRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    session_id: str = Field(default="web", max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    voice: bool = False


class ReviewRequest(BaseModel):
    code: str = Field(default="", max_length=120000)
    filename: str = Field(default="", max_length=200)


class SiteCheckRequest(BaseModel):
    url: str = Field(default="", max_length=500)
    analyse: bool = True


class MemoryRequest(BaseModel):
    text: str = Field(default="", max_length=600)
    tags: str = Field(default="", max_length=200)
    session_id: str = Field(default="web", max_length=64)


# ============================================================ yardımcılar

def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"


def _normalise_history(history: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("who") or item.get("role")
        role = "assistant" if role in {"bot", "assistant"} else "user"
        text = item.get("text") or item.get("content") or ""
        if not isinstance(text, str):
            continue
        text = clean_text(text, 2000)
        if text:
            out.append({"role": role, "text": text})
    return out[-12:]


async def _stream_response(question: str, session_id: str, context: dict, history: list[dict], voice: bool):
    async def generator() -> AsyncIterator[str]:
        try:
            async for event in agent.stream(
                question,
                session_id=session_id,
                context=context,
                history=history,
                voice=voice,
            ):
                yield _sse(event)
        except asyncio.CancelledError:  # istemci bağlantıyı kapattı
            raise
        except Exception as exc:  # pragma: no cover - beklenmeyen hata
            logger.exception("Akış hatası: %s", exc)
            yield _sse({"type": "error", "text": "Beklenmeyen bir hata oluştu, tekrar dener misin?"})

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(generator(), media_type="text/event-stream", headers=headers)


# ============================================================ sohbet

@app.get("/api/chat/stream")
async def chat_stream_get(
    q: str = Query(default="", max_length=4000),
    session_id: str = Query(default="web", max_length=64),
    voice: bool = Query(default=False),
    place: str | None = Query(default=None, max_length=200),
    weather: str | None = Query(default=None, max_length=300),
    battery: str | None = Query(default=None, max_length=100),
):
    context = {
        key: value
        for key, value in {"place": place, "weather": weather, "battery": battery}.items()
        if value
    }
    return await _stream_response(q, session_id, context, [], voice)


@app.post("/api/chat/stream")
async def chat_stream_post(body: AskRequest):
    return await _stream_response(
        body.question,
        body.session_id,
        body.context or {},
        _normalise_history(body.history),
        body.voice,
    )


@app.post("/api/ask")
async def ask(body: AskRequest):
    """Eski arayüzle uyumlu tek yanıt uç noktası."""
    question = clean_text(body.question)
    if not question:
        return {"answer": "Sorunu duyamadım, tekrar eder misin?"}
    try:
        result = await agent.answer(
            question,
            session_id=body.session_id,
            context=body.context or {},
            history=_normalise_history(body.history),
            voice=body.voice,
        )
    except ProviderError as exc:
        return {"answer": None, "error": str(exc)}
    return {
        "answer": result.answer,
        "sources": result.sources,
        "tools_used": result.tools_used,
        "provider": result.provider,
        "model": result.model,
    }


@app.post("/api/review")
async def review(body: ReviewRequest):
    code = (body.code or "").strip()
    if not code:
        return {"review": None, "error": "İncelenecek kod boş."}
    try:
        text = await agent.review_code(code, body.filename)
    except ProviderError as exc:
        return {"review": None, "error": str(exc)}
    return {"review": text}


@app.post("/api/site-check")
async def site_check(body: SiteCheckRequest):
    tool = agent.tools.get("check_site")
    if tool is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Site kontrol aracı yüklenemedi.")
    ctx = ToolContext(memory=memory, settings=settings, session_id="api")
    try:
        raw = await tool.handler(ctx, {"url": body.url})
    except (ToolError, SafetyError) as exc:
        return {"error": str(exc), "up": False}

    payload = {
        "url": raw.get("url"),
        "up": bool(raw.get("up")),
        "status": raw.get("status"),
        "responseTime": raw.get("response_ms"),
        "size": int((raw.get("size_kb") or 0) * 1024) or None,
        "title": raw.get("title"),
        "description": raw.get("description"),
        "lang": raw.get("lang"),
        "h1Count": raw.get("h1_count"),
        "https": raw.get("https"),
        "analysis": None,
    }
    if raw.get("error"):
        payload["error"] = raw["error"]
        return payload
    if body.analyse and payload["up"]:
        try:
            payload["analysis"] = await agent.analyse_site(
                "Adres: {url}\nHTTP: {status}\nYanıt: {ms} ms\nBaşlık: {title}\nDil: {lang}".format(
                    url=payload["url"],
                    status=payload["status"],
                    ms=payload["responseTime"],
                    title=payload["title"] or "(yok)",
                    lang=payload["lang"] or "(yok)",
                ),
                "",
            )
        except ProviderError:
            payload["analysis"] = None
    return payload


# ============================================================ hafıza

@app.get("/api/memory")
async def list_memory(session_id: str = Query(default="web", max_length=64), limit: int = Query(default=50, ge=1, le=200)):
    return {"session_id": session_id, "facts": memory.list_facts(session_id, limit=limit)}


@app.post("/api/memory")
async def add_memory(body: MemoryRequest):
    text = clean_text(body.text, 600)
    if len(text) < 3:
        raise HTTPException(status_code=400, detail="Not çok kısa.")
    record = memory.add_fact(text, session_id=body.session_id, tags=body.tags)
    return {"saved": True, "fact": record}


@app.delete("/api/memory")
async def clear_memory(
    session_id: str = Query(default="web", max_length=64),
    fact_id: int | None = Query(default=None),
    history: bool = Query(default=False),
):
    if fact_id is not None:
        return {"deleted": memory.delete_fact(fact_id)}
    removed = memory.clear_facts(session_id)
    messages = memory.clear_session(session_id) if history else 0
    return {"deleted_facts": removed, "deleted_messages": messages}


# ============================================================ meta

@app.get("/api/tools")
async def tools_catalogue():
    return {"tools": agent.tool_specs()}


@app.get("/api/health")
async def health():
    return {
        **settings.public(),
        "status": "ok",
        "mode": "demo" if provider.name == "offline" else "live",
        "memory": memory.stats(),
    }


# ============================================================ statik dosyalar

if settings.static_dir.exists():
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
else:  # pragma: no cover
    logger.warning("Statik dizin bulunamadı: %s", settings.static_dir)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
