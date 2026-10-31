"""LLM sağlayıcı soyutlaması.

Nova, sağlayıcıdan bağımsız tek bir iç mesaj formatı kullanır:

    {"role": "user", "text": "..."}
    {"role": "assistant", "text": "...", "tool_calls": [ToolCall, ...]}
    {"role": "tool", "call_id": "...", "name": "...", "result": {...}}

Desteklenen sağlayıcılar:
    anthropic : Claude (resmî SDK, araç kullanımı + akış)
    openai    : OpenAI uyumlu herhangi bir uç nokta (function calling + SSE)
    offline   : anahtar gerektirmeyen demo sağlayıcı; araç döngüsünü simüle eder
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings


class ProviderError(RuntimeError):
    """Sağlayıcı çağrısı başarısız olduğunda fırlatılır."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]: ...

    async def complete(self, system: str, user: str, *, max_tokens: int = 1200) -> str: ...


def _compact(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """İç formatı Anthropic'in içerik blokları formatına çevirir."""
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            text = (msg.get("text") or "").strip()
            if text:
                out.append({"role": "user", "content": [{"type": "text", "text": text}]})
        elif role == "assistant":
            blocks: list[dict] = []
            if (msg.get("text") or "").strip():
                blocks.append({"type": "text", "text": msg["text"].strip()})
            for call in msg.get("tool_calls") or []:
                blocks.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments or {}}
                )
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("call_id") or "unknown",
                "content": _compact(msg.get("result") or {}),
            }
            previous = out[-1] if out else None
            if (
                previous
                and previous["role"] == "user"
                and isinstance(previous["content"], list)
                and all(item.get("type") == "tool_result" for item in previous["content"])
            ):
                previous["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """İç formatı OpenAI uyumlu chat formatına çevirir."""
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            text = (msg.get("text") or "").strip()
            if text:
                out.append({"role": "user", "content": text})
        elif role == "assistant":
            calls = msg.get("tool_calls") or []
            entry: dict = {"role": "assistant", "content": (msg.get("text") or "").strip() or None}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": _compact(call.arguments or {})},
                    }
                    for call in calls
                ]
            if entry["content"] or entry.get("tool_calls"):
                out.append(entry)
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("call_id") or "unknown",
                    "content": _compact(msg.get("result") or {}),
                }
            )
    return out


# ============================================================ Anthropic

class AnthropicProvider:
    """Claude modelleri için resmî SDK tabanlı sağlayıcı."""

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - kurulum hatası
            raise ProviderError("anthropic paketi kurulu değil.") from exc
        if not settings.api_key:
            raise ProviderError("ANTHROPIC_API_KEY tanımlı değil.")
        kwargs: dict[str, Any] = {
            "api_key": settings.api_key,
            "timeout": settings.request_timeout + 30,
        }
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        if settings.ca_bundle:
            kwargs["http_client"] = httpx.AsyncClient(verify=settings.ca_bundle)
        self._client = AsyncAnthropic(**kwargs)
        self.model = settings.model
        self._max_tokens = settings.max_tokens
        self._effort = (settings.effort or "medium").lower()

    def _common(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            payload["tools"] = tools
        if self._effort in {"low", "medium", "high", "xhigh", "max"}:
            payload["output_config"] = {"effort": self._effort}
        return payload

    async def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        from anthropic import AnthropicError

        payload = self._common(system, messages, tools)
        try:
            async with self._client.messages.stream(**payload) as stream:
                async for chunk in stream.text_stream:
                    if chunk:
                        yield {"type": "delta", "text": chunk}
                final = await stream.get_final_message()
        except AnthropicError as exc:
            raise ProviderError(_anthropic_error_text(exc)) from exc

        turn = AssistantTurn(stop_reason=getattr(final, "stop_reason", None))
        for block in final.content or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                turn.text += getattr(block, "text", "") or ""
            elif block_type == "tool_use":
                turn.tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", "") or "",
                        name=getattr(block, "name", "") or "",
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
        usage = getattr(final, "usage", None)
        if usage is not None:
            turn.usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
        yield {"type": "turn", "turn": turn}

    async def complete(self, system: str, user: str, *, max_tokens: int = 1200) -> str:
        from anthropic import AnthropicError

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
        }
        if self._effort in {"low", "medium", "high", "xhigh", "max"}:
            payload["output_config"] = {"effort": self._effort}
        try:
            message = await self._client.messages.create(**payload)
        except AnthropicError as exc:
            raise ProviderError(_anthropic_error_text(exc)) from exc
        return "".join(getattr(block, "text", "") or "" for block in message.content or []).strip()


def _anthropic_error_text(exc: Exception) -> str:
    name = type(exc).__name__
    message = str(exc)
    if "authentication" in name.lower() or "401" in message:
        return "API anahtarı geçersiz görünüyor (401)."
    if "rate" in name.lower() or "429" in message:
        return "İstek sınırı aşıldı (429). Biraz sonra tekrar dene."
    if "connection" in name.lower() or "timeout" in name.lower():
        return "Model servisine ulaşılamadı (bağlantı/zaman aşımı)."
    return "Model servisi hata verdi: " + (message[:160] or name)


# ============================================================ OpenAI uyumlu

class OpenAIProvider:
    """OpenAI ve uyumlu uç noktalar (vLLM, Ollama, LM Studio, OpenRouter...)."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ProviderError("OPENAI_API_KEY tanımlı değil.")
        self.model = settings.model
        self._key = settings.api_key
        self._base = (settings.base_url or "https://api.openai.com/v1").rstrip("/")
        self._max_tokens = settings.max_tokens
        self._temperature = settings.temperature
        self._timeout = settings.request_timeout + 30
        self._verify: bool | str = settings.ca_bundle or True

    def _headers(self) -> dict:
        return {"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}

    async def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *to_openai_messages(messages)],
            "stream": True,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
            payload["tool_choice"] = "auto"

        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish_reason: str | None = None
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client,
                client.stream(
                    "POST", self._base + "/chat/completions", json=payload, headers=self._headers()
                ) as response,
            ):
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise ProviderError(f"Model servisi {response.status_code} döndü: {body[:160]}")
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data in {"", "[DONE]"}:
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            text_parts.append(piece)
                            yield {"type": "delta", "text": piece}
                        for raw_call in delta.get("tool_calls") or []:
                            index = int(raw_call.get("index", 0))
                            slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if raw_call.get("id"):
                                slot["id"] = raw_call["id"]
                            function = raw_call.get("function") or {}
                            if function.get("name"):
                                slot["name"] += function["name"]
                            if function.get("arguments"):
                                slot["arguments"] += function["arguments"]
        except httpx.HTTPError as exc:
            raise ProviderError("Model servisine ulaşılamadı: " + type(exc).__name__) from exc

        turn = AssistantTurn(text="".join(text_parts).strip(), stop_reason=finish_reason)
        for index in sorted(calls):
            slot = calls[index]
            if not slot["name"]:
                continue
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": slot["arguments"][:500]}
            turn.tool_calls.append(
                ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=arguments or {})
            )
        yield {"type": "turn", "turn": turn}

    async def complete(self, system: str, user: str, *, max_tokens: int = 1200) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
                response = await client.post(
                    self._base + "/chat/completions", json=payload, headers=self._headers()
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Model servisi hatası: " + type(exc).__name__) from exc
        choices = data.get("choices") or []
        if not choices:
            return ""
        return ((choices[0].get("message") or {}).get("content") or "").strip()


# ============================================================ çevrimdışı demo

_MATH_RE = re.compile(r"\d[\d\s.,+\-*/^()%]*\d")
_CITY_HINTS = (
    "adana", "adıyaman", "afyon", "ağrı", "amasya", "ankara", "antalya", "aydın",
    "balıkesir", "batman", "bilecik", "bingöl", "bitlis", "bolu", "bursa", "çanakkale",
    "çankırı", "çorum", "denizli", "diyarbakır", "edirne", "elazığ", "erzincan",
    "erzurum", "eskişehir", "gaziantep", "giresun", "gümüşhane", "hakkari", "hatay",
    "ısparta", "isparta", "istanbul", "izmir", "kars", "kastamonu", "kayseri", "kocaeli",
    "konya", "kütahya", "malatya", "manisa", "mardin", "mersin", "muğla", "muş",
    "nevşehir", "niğde", "ordu", "rize", "sakarya", "samsun", "siirt", "sinop", "sivas",
    "tekirdağ", "tokat", "trabzon", "tunceli", "urfa", "uşak", "van", "yalova", "yozgat",
    "zonguldak", "london", "paris", "berlin", "roma", "madrid", "moskova", "tokyo",
    "new york", "washington", "pekin", "atina",
)


def _stream_words(text: str, size: int = 3):
    words = text.split(" ")
    for index in range(0, len(words), size):
        piece = " ".join(words[index : index + size])
        if index:
            piece = " " + piece
        if piece:
            yield piece


def _context_place(system: str) -> str | None:
    match = re.search(r"^Konum:\s*(.+)$", system or "", re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_city(question: str, system: str) -> str | None:
    lowered = question.lower()
    for city in sorted(_CITY_HINTS, key=len, reverse=True):
        if city in lowered:
            return city.title().replace("Istanbul", "İstanbul").replace("Izmir", "İzmir")
    place = _context_place(system)
    if place:
        return place.split(",")[0].strip()
    return None


def _extract_expression(question: str) -> str | None:
    text = question.lower()
    text = text.replace("karekök", " sqrt ").replace("kare kökü", " sqrt ")
    text = text.replace("kere", " * ").replace("çarpı", " * ").replace("bölü", " / ")
    text = text.replace("artı", " + ").replace("eksi", " - ").replace("üssü", " ** ")
    text = text.replace("yüzde", " % ")
    match = _MATH_RE.search(text)
    if not match:
        return None
    expr = match.group(0).strip().rstrip(".,")
    if not re.search(r"[+\-*/^%]", expr):
        return None
    return expr.replace(",", ".")


class OfflineProvider:
    """Anahtar gerektirmeyen demo sağlayıcı.

    Gerçek bir model çağırmaz; niyet tespiti yapıp aynı araç döngüsünü kullanır.
    Böylece arayüz, araçlar ve ajan akışı API anahtarı olmadan da çalışır ve
    testler tamamen ağsız (hermetik) koşabilir.
    """

    name = "offline"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.model or "nova-local-v2"

    async def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        if messages and messages[-1].get("role") == "tool":
            text = summarize_tool_round(messages)
            for piece in _stream_words(text):
                yield {"type": "delta", "text": piece}
            yield {"type": "turn", "turn": AssistantTurn(text=text, stop_reason="end_turn")}
            return

        question = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                question = message.get("text") or ""
                break
        available = {tool["name"] for tool in tools}
        plan = _plan(question, system, available)
        if plan:
            yield {
                "type": "turn",
                "turn": AssistantTurn(
                    text=plan.get("say", ""),
                    tool_calls=plan["calls"],
                    stop_reason="tool_use",
                ),
            }
            return

        text = (
            "Şu anda demo modunda çalışıyorum, yani gerçek bir dil modeline bağlı değilim. "
            "Hava durumu, tarih ve saat, hesaplama, web araması, site kontrolü ve hafıza araçlarımı "
            "kullanabiliyorum. Tam yapay zekâ yanıtları için sunucuda ANTHROPIC_API_KEY tanımlaman yeterli."
        )
        for piece in _stream_words(text):
            yield {"type": "delta", "text": piece}
        yield {"type": "turn", "turn": AssistantTurn(text=text, stop_reason="end_turn")}

    async def complete(self, system: str, user: str, *, max_tokens: int = 1200) -> str:
        if "kod" in (system or "").lower():
            return self._code_review(user)
        return (
            "Demo modunda ayrıntılı değerlendirme üretemiyorum. "
            "Gerçek model yanıtları için ANTHROPIC_API_KEY tanımlanmalı."
        )

    @staticmethod
    def _code_review(payload: str) -> str:
        code = payload.split("\n\n", 1)[-1]
        lines = code.splitlines() or [""]
        long_lines = [index + 1 for index, line in enumerate(lines) if len(line) > 120]
        todos = code.count("TODO") + code.count("FIXME")
        risks = []
        for pattern, label in (
            ("eval(", "eval() kullanımı"),
            ("exec(", "exec() kullanımı"),
            ("innerHTML", "innerHTML ile HTML basımı"),
            ("SELECT *", "SELECT * sorgusu"),
            ("except:", "çıplak except"),
        ):
            if pattern in code:
                risks.append(label)
        parts = [
            f"Kod yaklaşık {len(lines)} satır. Demo modunda yalnızca statik kontroller yapabiliyorum.",
            f"Uzun satır sayısı (>120 karakter): {len(long_lines)}." if long_lines else "Uzun satır yok, satır genişlikleri makul.",
            f"TODO/FIXME notu: {todos}." if todos else "Açık TODO notu görünmüyor.",
        ]
        if risks:
            parts.append("Dikkat edilmesi gereken kalıplar: " + ", ".join(risks) + ".")
        else:
            parts.append("Bilinen riskli kalıp (eval, exec, çıplak except) bulunmadı.")
        parts.append("Ayrıntılı inceleme için gerçek model bağlantısı gerekli.")
        return "\n".join("- " + part for part in parts)


def _plan(question: str, system: str, available: set[str]) -> dict | None:
    q = (question or "").lower()
    calls: list[ToolCall] = []

    def add(name: str, arguments: dict) -> None:
        if name in available:
            calls.append(ToolCall(id="demo_" + name + "_" + str(len(calls)), name=name, arguments=arguments))

    if any(word in q for word in ("benim hakkımda", "hakkimda", "ne biliyorsun", "hatırlıyor musun", "hatirliyor musun")):
        add("memory_search", {"query": question})
    elif any(word in q for word in ("hatırla", "hatirla", "unutma", "aklında tut", "aklinda tut", "kaydet")):
        add("memory_save", {"text": question})

    if any(word in q for word in ("hava", "sıcaklık", "sicaklik", "yağmur", "yagmur", "kar yağ", "rüzgar", "ruzgar", "derece")):
        city = _extract_city(question, system)
        add("get_weather", {"city": city} if city else {})

    if any(word in q for word in ("saat kaç", "saat kac", "saat", "tarih", "günlerden", "gunlerden", "bugün ayın", "hangi gün")):
        add("current_datetime", {})

    expression = _extract_expression(question)
    if expression:
        add("calculate", {"expression": expression})

    domain = re.search(r"((?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|tr|app|ai|co|me)(?:/[^\s]*)?)", q)
    if domain and any(word in q for word in ("kontrol", "çalışıyor mu", "calisiyor mu", "açık mı", "durum")):
        add("check_site", {"url": domain.group(1)})

    # Genel bilgi araması: yalnızca başka bir araç zaten seçilmediyse ve
    # soru bir hesaplama değilse devreye girer.
    search_hints = ("nedir", "kimdir", "kim ", "nerede", "araştır", "arastir", "haber", "kaç ", "ne zaman")
    if not calls and not expression and any(word in q for word in search_hints):
        add("web_search", {"query": question})

    if not calls:
        return None
    return {"say": "", "calls": calls}


def summarize_tool_round(messages: list[dict]) -> str:
    """Araç sonuçlarını doğal Türkçe cümlelere çevirir (demo sağlayıcı)."""
    sentences: list[str] = []
    for message in messages[-6:]:
        if message.get("role") != "tool":
            continue
        name = message.get("name") or ""
        result = message.get("result") or {}
        error = result.get("error") or result.get("_tool_error")
        if error:
            sentences.append(f"{name} aracını çalıştıramadım: {error}")
            continue
        if name == "get_weather":
            forecast = (result.get("forecast") or [{}])[0]
            sentences.append(
                f"{result.get('place', 'Konumunda')} şu anda {result.get('temperature')} derece ve hava "
                f"{result.get('condition')}. Hissedilen {result.get('feels_like')} derece, nem yüzde "
                f"{result.get('humidity')}, rüzgar saatte {result.get('wind_kmh')} kilometre. "
                f"Yarın en yüksek {forecast.get('max')} derece, hava {forecast.get('condition')}."
            )
        elif name == "calculate":
            sentences.append(f"Cevap {result.get('formatted')}.")
        elif name == "current_datetime":
            sentences.append(f"Şu anda {result.get('spoken')}.")
        elif name == "web_search":
            results = result.get("results") or []
            if results:
                first = results[0]
                snippet = (first.get("snippet") or "").split(". ")
                summary = ". ".join(snippet[:2]).strip()
                if not summary.endswith("."):
                    summary += "."
                sentences.append(f"{first.get('title')} hakkında bulduklarım: {summary} Kaynak: {first.get('source')}.")
            else:
                sentences.append("Web'de güvenilir bir sonuç bulamadım.")
        elif name == "check_site":
            if result.get("up"):
                sentences.append(
                    f"{result.get('url')} çalışıyor, HTTP {result.get('status')}, yanıt süresi "
                    f"{result.get('response_ms')} milisaniye. Sayfa başlığı: {result.get('title') or 'yok'}."
                )
            else:
                sentences.append(f"{result.get('url')} şu anda erişilemiyor.")
        elif name == "memory_save":
            sentences.append("Bunu hafızama kaydettim." if result.get("saved") else "Kaydedemedim.")
        elif name == "memory_search":
            facts = result.get("facts") or []
            if facts:
                sentences.append("Hafızamda şunlar var: " + "; ".join(f.get("text", "") for f in facts[:3]) + ".")
            else:
                sentences.append("Hafızamda bununla ilgili kayıt yok.")
    return " ".join(sentences) or "Araçtan sonuç alamadım."


# ============================================================ fabrika

def build_provider(settings: Settings) -> Provider:
    """Ayarlara göre sağlayıcı kurar; başarısız olursa demo moduna düşer."""
    if settings.provider == "anthropic":
        try:
            return AnthropicProvider(settings)
        except ProviderError:
            return OfflineProvider(settings)
    if settings.provider == "openai":
        try:
            return OpenAIProvider(settings)
        except ProviderError:
            return OfflineProvider(settings)
    return OfflineProvider(settings)
