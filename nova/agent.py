"""Nova ajanı.

Görev: kullanıcı sorusunu, hafıza + tarayıcı bağlamıyla birleştirip modelin
gerektiğinde araç çağırmasına izin veren çok adımlı bir döngü yürütmek ve
sonucu olay (event) akışı olarak dışarı vermek.

Olay türleri:
    start       : oturum/sağlayıcı bilgisi
    status      : kullanıcıya gösterilecek kısa durum metni
    tool_start  : araç çağrısı başladı
    tool_result : araç çağrısı bitti (özet ile)
    delta       : yanıt metninin bir parçası (akış)
    done        : nihai yanıt, kaynaklar, kullanılan araçlar
    error       : kullanıcıya gösterilebilir hata
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from .config import Settings
from .llm import AssistantTurn, Provider, ProviderError, ToolCall
from .memory import MemoryStore
from .prompts import CODE_REVIEW_PROMPT, SITE_ANALYSIS_PROMPT, build_system_prompt
from .safety import SafetyError, clean_text, clip
from .tools import Tool, ToolContext, ToolError, build_tools, tool_specs

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 6000
MAX_MESSAGE_CHARS = 2000


@dataclass
class AgentResult:
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    tools_used: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": self.sources,
            "tools_used": self.tools_used,
            "provider": self.provider,
            "model": self.model,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
        }


class NovaAgent:
    """Araç kullanabilen, hafızalı Türkçe asistan."""

    def __init__(
        self,
        provider: Provider,
        memory: MemoryStore,
        settings: Settings,
        tools: dict[str, Tool] | None = None,
    ) -> None:
        self.provider = provider
        self.memory = memory
        self.settings = settings
        self.tools = tools if tools is not None else build_tools()

    # ------------------------------------------------------------ yardımcı
    def tool_specs(self) -> list[dict]:
        return tool_specs(self.tools)

    def _build_messages(
        self,
        question: str,
        session_id: str,
        history: list[dict] | None,
    ) -> list[dict]:
        messages: list[dict] = []
        source = history if history else self.memory.recent_messages(session_id, self.settings.history_limit)
        budget = 8000
        for item in (source or [])[-self.settings.history_limit :]:
            role = item.get("role")
            if role is None:
                # İstemci geçmişi "who" alanıyla da gönderebilir (v1 uyumluluğu).
                who = item.get("who")
                role = "assistant" if who in {"bot", "assistant"} else "user" if who else None
            if role not in {"user", "assistant"}:
                continue
            text = clean_text(str(item.get("text") or item.get("content") or ""), MAX_MESSAGE_CHARS)
            if not text:
                continue
            if budget - len(text) < 0:
                break
            budget -= len(text)
            messages.append({"role": role, "text": text})
        messages.append({"role": "user", "text": question})
        return messages

    async def _run_tool(self, call: ToolCall, ctx: ToolContext) -> dict:
        tool = self.tools.get(call.name)
        if tool is None:
            return {"error": f"{call.name} diye bir aracım yok."}
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        try:
            outcome = tool.handler(ctx, arguments)
            # Hem async hem sync araçlar desteklenir; sync olanlar iş parçacığına taşınır.
            if inspect.isawaitable(outcome):
                result = await outcome
            else:
                result = await asyncio.to_thread(lambda: outcome)
            return result if isinstance(result, dict) else {"result": result}
        except (ToolError, SafetyError) as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - beklenmeyen araç hatası
            logger.warning("Araç hatası (%s): %s", call.name, exc)
            return {"error": "Araç beklenmeyen bir hata verdi."}

    @staticmethod
    def _summarize_tool(name: str, result: dict) -> str:
        if result.get("error"):
            return clip(str(result["error"]), 120)
        if name == "get_weather":
            return f"{result.get('place', '')} {result.get('temperature')}°C, {result.get('condition')}".strip()
        if name == "calculate":
            return "= " + str(result.get("formatted"))
        if name == "current_datetime":
            return str(result.get("spoken") or result.get("time") or "")
        if name == "web_search":
            return f"{len(result.get('results') or [])} sonuç"
        if name == "check_site":
            return f"HTTP {result.get('status')} · {result.get('response_ms')} ms" if result.get("up") else "erişilemiyor"
        if name == "memory_save":
            return "kaydedildi" if result.get("saved") else "kaydedilemedi"
        if name == "memory_search":
            return f"{result.get('count', 0)} not"
        return "tamam"

    @staticmethod
    def _collect_sources(name: str, result: dict, sources: list[dict]) -> None:
        if name == "web_search":
            for item in result.get("results") or []:
                url = item.get("url")
                if url and len(sources) < 4 and all(existing.get("url") != url for existing in sources):
                    sources.append(
                        {
                            "title": item.get("title"),
                            "url": url,
                            "source": item.get("source"),
                        }
                    )
        elif name == "check_site" and result.get("url"):
            sources.append({"title": result.get("title") or result["url"], "url": result["url"], "source": "Site kontrolü"})

    # ------------------------------------------------------------ ana akış
    async def stream(
        self,
        question: str,
        *,
        session_id: str = "web",
        context: dict | None = None,
        history: list[dict] | None = None,
        voice: bool = False,
    ) -> AsyncIterator[dict]:
        session_id = (session_id or "web")[:64]
        try:
            clean_question = clean_text(question)
        except SafetyError as exc:
            yield {"type": "error", "text": str(exc)}
            return
        if not clean_question:
            yield {"type": "error", "text": "Sorunu duyamadım, tekrar eder misin?"}
            return

        yield {"type": "start", "provider": self.provider.name, "model": self.provider.model, "session_id": session_id}

        memories = self.memory.search_facts(clean_question, session_id, limit=5)
        system = build_system_prompt(voice=voice, context=context, memories=memories)
        messages = self._build_messages(clean_question, session_id, history)
        ctx = ToolContext(memory=self.memory, settings=self.settings, session_id=session_id)
        tools = self.tool_specs()

        result = AgentResult(provider=self.provider.name, model=self.provider.model)
        answer_parts: list[str] = []
        last_turn: AssistantTurn | None = None

        for _ in range(max(1, self.settings.max_tool_rounds)):
            try:
                turn: AssistantTurn | None = None
                async for event in self.provider.stream_turn(system, messages, tools):
                    if event.get("type") == "delta":
                        piece = event.get("text") or ""
                        if piece:
                            answer_parts.append(piece)
                            yield {"type": "delta", "text": piece}
                    elif event.get("type") == "turn":
                        turn = event.get("turn")
            except ProviderError as exc:
                logger.warning("Sağlayıcı hatası: %s", exc)
                yield {"type": "error", "text": str(exc)}
                break
            if turn is None:
                break
            last_turn = turn
            if turn.usage:
                result.usage = turn.usage
            if not turn.tool_calls:
                break

            # Modelin metni ve araç çağrıları tek bir asistan turunda toplanır.
            messages.append({"role": "assistant", "text": turn.text, "tool_calls": turn.tool_calls})

            for call in turn.tool_calls:
                tool = self.tools.get(call.name)
                label = (tool.status_text if tool else "Araç çalıştırıyorum") + "…"
                yield {"type": "tool_start", "name": call.name, "label": label}
                tool_result = await self._run_tool(call, ctx)
                self._collect_sources(call.name, tool_result, result.sources)
                result.tools_used.append(
                    {
                        "name": call.name,
                        "ok": not bool(tool_result.get("error")),
                        "summary": self._summarize_tool(call.name, tool_result),
                    }
                )
                yield {
                    "type": "tool_result",
                    "name": call.name,
                    "ok": not bool(tool_result.get("error")),
                    "summary": self._summarize_tool(call.name, tool_result),
                }
                payload = json.loads(clip(json.dumps(tool_result, ensure_ascii=False, default=str), MAX_TOOL_RESULT_CHARS))
                messages.append({"role": "tool", "call_id": call.id, "name": call.name, "result": payload})

        # Araç çağrısıyla biten tur: araçsız son bir yanıt iste
        if last_turn is not None and last_turn.tool_calls and not answer_parts:
            try:
                async for event in self.provider.stream_turn(system, messages, []):
                    if event.get("type") == "delta" and event.get("text"):
                        answer_parts.append(event["text"])
                        yield {"type": "delta", "text": event["text"]}
                    elif event.get("type") == "turn":
                        last_turn = event.get("turn") or last_turn
            except ProviderError as exc:
                yield {"type": "error", "text": str(exc)}

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = (
                "Bunu şu anda yanıtlayamadım. Hava durumu, saat, hesap, web araması ve hafıza "
                "konularında yardımcı olabilirim; soruyu biraz farklı sorar mısın?"
            )
            yield {"type": "delta", "text": answer}

        result.answer = answer
        result.stop_reason = getattr(last_turn, "stop_reason", None)

        try:
            self.memory.append_message(session_id, "user", clean_question)
            self.memory.append_message(session_id, "assistant", answer)
        except Exception as exc:  # pragma: no cover - disk hatası
            logger.warning("Hafızaya yazılamadı: %s", exc)

        yield {"type": "done", **result.as_dict()}

    async def answer(
        self,
        question: str,
        *,
        session_id: str = "web",
        context: dict | None = None,
        history: list[dict] | None = None,
        voice: bool = False,
    ) -> AgentResult:
        """Akışı tüketip tek bir sonuç döndürür (akış desteklemeyen istemciler)."""
        final = AgentResult(provider=self.provider.name, model=self.provider.model)
        async for event in self.stream(
            question, session_id=session_id, context=context, history=history, voice=voice
        ):
            if event.get("type") == "done":
                final = AgentResult(
                    answer=event.get("answer") or "",
                    sources=event.get("sources") or [],
                    tools_used=event.get("tools_used") or [],
                    provider=event.get("provider") or self.provider.name,
                    model=event.get("model") or self.provider.model,
                    stop_reason=event.get("stop_reason"),
                    usage=event.get("usage") or {},
                )
        return final

    # ------------------------------------------------------------ yardımcı uçlar
    async def review_code(self, code: str, filename: str = "") -> str:
        header = "İncelenecek dosya: " + (filename or "belirtilmedi") + "\n\n"
        return await self.provider.complete(CODE_REVIEW_PROMPT, header + clip(code, 60000), max_tokens=1500)

    async def analyse_site(self, facts: str, snippet: str) -> str:
        payload = facts + "\n\nSayfanın HTML kodu (ilk bölüm):\n" + clip(snippet, 12000)
        return await self.provider.complete(SITE_ANALYSIS_PROMPT, payload, max_tokens=700)
