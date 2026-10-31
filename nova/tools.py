"""Nova'nın araçları (function calling).

Her araç iki parçadan oluşur:
    - JSON şeması  : modele "ne zaman, hangi parametrelerle" çağıracağını anlatır
    - async handler: gerçek işi yapar, JSON'a çevrilebilir sözlük döndürür

Ağ erişimi olmayan ortamlarda araçlar hata döndürür; ajan bunu kullanıcıya
dürüstçe aktarır (uydurmaz).
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
import operator
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .config import Settings
from .memory import MemoryStore
from .safety import assert_public_url, clip

USER_AGENT = "NovaAsistan/2.0 (+https://github.com/kcagatay0746-hash/nova)"
HTTP_TIMEOUT = httpx.Timeout(12.0, connect=6.0)

WMO_TR = {
    0: "açık", 1: "az bulutlu", 2: "parçalı bulutlu", 3: "kapalı",
    45: "sisli", 48: "kırağılı sis", 51: "hafif çisenti", 53: "çisenti",
    55: "yoğun çisenti", 56: "dondurucu çisenti", 57: "yoğun dondurucu çisenti",
    61: "hafif yağmurlu", 63: "yağmurlu", 65: "şiddetli yağmurlu",
    66: "dondurucu yağmur", 67: "şiddetli dondurucu yağmur",
    71: "hafif kar yağışlı", 73: "kar yağışlı", 75: "yoğun kar yağışlı",
    77: "kar taneleri", 80: "hafif sağanak", 81: "sağanak", 82: "şiddetli sağanak",
    85: "kar sağanağı", 86: "yoğun kar sağanağı", 95: "gök gürültülü fırtına",
    96: "dolulu fırtına", 99: "şiddetli dolulu fırtına",
}


def weather_text(code: int | None) -> str:
    return WMO_TR.get(int(code or 0), "bilinmeyen hava durumu")


class ToolError(RuntimeError):
    """Araç çalışırken oluşan, kullanıcıya aktarılabilir hata."""


@dataclass
class ToolContext:
    """Araçların ihtiyaç duyduğu bağımlılıklar."""

    memory: MemoryStore
    settings: Settings
    session_id: str = "default"


Handler = Callable[[ToolContext, dict], Awaitable[dict]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Handler
    status_text: str = ""

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


# ============================================================ hesap makinesi

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "min": min,
    "max": max,
    "pow": math.pow,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_MAX_EXPONENT = 10000
_MAX_NODES = 120


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError("Yalnızca sayılar kullanılabilir.")
        return node.value  # int/float ayrımı korunur
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ToolError("Üs çok büyük.")
        if isinstance(node.op, ast.Pow) and abs(left) > 1e6 and right > 100:
            raise ToolError("Sonuç çok büyük olurdu.")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ToolError("Sıfıra bölme tanımsızdır.")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        if node.keywords:
            raise ToolError("Anahtar kelimeli argüman desteklenmiyor.")
        args = [_eval_node(arg) for arg in node.args]
        if len(args) > 8:
            raise ToolError("Çok fazla argüman.")
        try:
            return float(_FUNCS[node.func.id](*args))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ToolError("Fonksiyon hesaplanamadı: " + str(exc)[:80]) from exc
    raise ToolError("İfadede desteklenmeyen bir öğe var.")


def _eval_expression(expr: str) -> float:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ToolError("İfade anlaşılamadı.") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ToolError("İfade çok karmaşık.")
    try:
        return float(_eval_node(tree))
    except OverflowError as exc:
        raise ToolError("Sonuç çok büyük.") from exc


def safe_calculate(expression: str) -> float:
    """AST tabanlı güvenli hesap: eval/exec kullanmaz.

    Türkçe ondalık virgülü de desteklenir: önce ifade olduğu gibi denenir
    (böylece ``round(2.567, 2)`` gibi fonksiyon argümanları bozulmaz), olmazsa
    virgüller ondalık ayırıcı kabul edilerek yeniden denenir.
    """
    expr = (expression or "").strip()
    if not expr:
        raise ToolError("Hesaplanacak ifade boş.")
    if len(expr) > 300:
        raise ToolError("İfade çok uzun.")
    expr = expr.replace("^", "**")

    candidates = [expr]
    if "," in expr:
        candidates.append(expr.replace(",", "."))

    last_error: ToolError | None = None
    for candidate in candidates:
        try:
            value = _eval_expression(candidate)
        except ToolError as exc:
            last_error = exc
            continue
        if not math.isfinite(value):
            raise ToolError("Sonuç sonlu bir sayı değil.")
        return value
    raise last_error or ToolError("İfade anlaşılamadı.")


def format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return str(round(value, 6)).rstrip("0").rstrip(".").replace(".", ",")


# ============================================================ HTTP yardımcı

def _verify(settings: Settings) -> bool | str:
    """httpx doğrulama ayarı: özel CA dosyası varsa onu, yoksa sistem varsayılanını kullanır."""
    return settings.ca_bundle or True


async def _get_json(
    url: str,
    params: dict | None = None,
    *,
    timeout: float = 10.0,
    verify: bool | str = True,
) -> Any:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            verify=verify,
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise ToolError("Ağ isteği başarısız: " + type(exc).__name__) from exc
    except json.JSONDecodeError as exc:
        raise ToolError("Sunucu geçersiz JSON döndürdü.") from exc


# ============================================================ hava durumu

async def _geocode(city: str, verify: bool | str = True) -> dict:
    data = await _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": city, "count": 1, "language": "tr", "format": "json"},
        verify=verify,
    )
    results = (data or {}).get("results") or []
    if not results:
        raise ToolError("Bu şehir bulunamadı: " + city)
    top = results[0]
    parts: list[str] = []
    for part in (top.get("name"), top.get("admin1"), top.get("country")):
        if part and part not in parts:
            parts.append(part)
    label = ", ".join(parts)
    return {"lat": top["latitude"], "lon": top["longitude"], "place": label}


async def get_weather(ctx: ToolContext, args: dict) -> dict:
    verify = _verify(ctx.settings)
    city = (args.get("city") or "").strip()
    lat, lon = args.get("lat"), args.get("lon")
    place = city
    if lat is None or lon is None:
        if not city:
            raise ToolError("Şehir ya da koordinat gerekli.")
        geo = await _geocode(city, verify)
        lat, lon, place = geo["lat"], geo["lon"], geo["place"]
    data = await _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 4,
            "timezone": "auto",
        },
        verify=verify,
    )
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    days = []
    for index in range(1, min(4, len(daily.get("time") or []))):
        days.append(
            {
                "date": daily["time"][index],
                "condition": weather_text(daily["weather_code"][index]),
                "max": round(daily["temperature_2m_max"][index]),
                "min": round(daily["temperature_2m_min"][index]),
                "precipitation_chance": (daily.get("precipitation_probability_max") or [None] * 4)[index],
            }
        )
    return {
        "place": place or "bilinmeyen konum",
        "temperature": round(current.get("temperature_2m", 0)),
        "feels_like": round(current.get("apparent_temperature", 0)),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": round(current.get("wind_speed_10m", 0)),
        "condition": weather_text(current.get("weather_code")),
        "is_day": bool(current.get("is_day", 1)),
        "forecast": days,
        "source": "Open-Meteo",
    }


# ============================================================ web araması

async def _wikipedia(query: str, lang: str, verify: bool | str = True) -> dict | None:
    try:
        search = await _get_json(
            f"https://{lang}.wikipedia.org/w/api.php",
            {"action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 3},
            verify=verify,
        )
    except ToolError:
        return None
    hits = ((search or {}).get("query") or {}).get("search") or []
    if not hits:
        return None
    best = hits[0]
    try:
        detail = await _get_json(
            f"https://{lang}.wikipedia.org/w/api.php",
            {
                "action": "query", "format": "json", "prop": "extracts",
                "exintro": 1, "explaintext": 1, "pageids": best["pageid"],
            },
            verify=verify,
        )
    except ToolError:
        return None
    pages = ((detail or {}).get("query") or {}).get("pages") or {}
    page = pages.get(str(best["pageid"])) or {}
    extract = " ".join((page.get("extract") or "").split())
    if len(extract) < 40:
        return None
    return {
        "title": best.get("title"),
        "snippet": clip(extract, 900),
        "url": f"https://{lang}.wikipedia.org/?curid={best['pageid']}",
        "source": "Vikipedi (" + lang + ")",
    }


async def web_search(ctx: ToolContext, args: dict) -> dict:
    query = " ".join((args.get("query") or "").split())
    if not query:
        raise ToolError("Arama sorgusu boş.")
    limit = max(1, min(int(args.get("limit") or 4), 6))
    verify = _verify(ctx.settings)
    results: list[dict] = []

    for lang in ("tr", "en"):
        item = await _wikipedia(query, lang, verify)
        if item:
            results.append(item)
            break

    try:
        ddg = await _get_json(
            "https://api.duckduckgo.com/",
            {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            verify=verify,
        )
        if isinstance(ddg, dict):
            if ddg.get("AbstractText"):
                results.append(
                    {
                        "title": ddg.get("Heading") or query,
                        "snippet": clip(ddg["AbstractText"], 900),
                        "url": ddg.get("AbstractURL") or "",
                        "source": ddg.get("AbstractSource") or "DuckDuckGo",
                    }
                )
            for topic in (ddg.get("RelatedTopics") or [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(
                        {
                            "title": clip(topic["Text"], 80),
                            "snippet": clip(topic["Text"], 400),
                            "url": topic.get("FirstURL") or "",
                            "source": "DuckDuckGo",
                        }
                    )
    except ToolError:
        pass

    if not results:
        return {"query": query, "results": [], "note": "Güvenilir sonuç bulunamadı."}
    return {"query": query, "results": results[:limit]}


# ============================================================ tarih / saat

def current_datetime(ctx: ToolContext, args: dict) -> dict:
    tz_name = (args.get("timezone") or "Europe/Istanbul").strip()
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("Europe/Istanbul")
        tz_name = "Europe/Istanbul"
    now = datetime.now(UTC).astimezone(tz)
    weekdays = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    months = [
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    ]
    return {
        "timezone": tz_name,
        "iso": now.isoformat(timespec="seconds"),
        "time": now.strftime("%H:%M"),
        "date": f"{now.day} {months[now.month - 1]} {now.year}",
        "weekday": weekdays[now.weekday()],
        "spoken": f"{now.day} {months[now.month - 1]} {now.year} {weekdays[now.weekday()]}, saat {now.strftime('%H.%M')}",
    }


# ============================================================ site kontrolü

# Not: bazı sayfalar öznitelikleri tırnaksız yazar (lang=en gibi).
_META_RE = re.compile(
    r"<meta[^>]*name=[\"']?description[\"']?[^>]*content=(\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LANG_RE = re.compile(r"<html[^>]*\blang\s*=\s*[\"']?([a-zA-Z-]+)", re.IGNORECASE)
_H1_RE = re.compile(r"<h1[\s>]", re.IGNORECASE)


def parse_html_meta(html: str) -> dict:
    """HTML'den başlık, açıklama, dil ve H1 sayısını çıkarır."""
    title_match = _TITLE_RE.search(html)
    desc_match = _META_RE.search(html)
    lang_match = _LANG_RE.search(html)
    description = None
    if desc_match:
        description = desc_match.group(1).strip().strip("\"'")
    return {
        "title": clip(" ".join(title_match.group(1).split()), 160) if title_match else None,
        "description": clip(" ".join(description.split()), 240) if description else None,
        "lang": lang_match.group(1) if lang_match else None,
        "h1_count": len(_H1_RE.findall(html)),
    }


async def check_site(ctx: ToolContext, args: dict) -> dict:
    raw_url = args.get("url") or ""
    url = await assert_public_url(raw_url, allow_private=ctx.settings.allow_private_hosts)
    started = asyncio.get_running_loop().time()
    try:
        async with httpx.AsyncClient(
            timeout=ctx.settings.request_timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            verify=_verify(ctx.settings),
        ) as client:
            response = await client.get(url)
            body = response.content[:300_000]
    except httpx.HTTPError as exc:
        return {
            "url": url, "up": False,
            "error": "Bağlantı kurulamadı: " + type(exc).__name__,
        }
    elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
    html = body.decode(response.encoding or "utf-8", errors="replace")
    return {
        "url": str(response.url),
        "up": response.status_code < 400,
        "status": response.status_code,
        "response_ms": elapsed_ms,
        "size_kb": round(len(body) / 1024, 1),
        "https": str(response.url).startswith("https://"),
        **parse_html_meta(html),
        "server": response.headers.get("server"),
    }


# ============================================================ hafıza araçları

async def memory_save(ctx: ToolContext, args: dict) -> dict:
    text = (args.get("text") or "").strip()
    if len(text) < 3:
        raise ToolError("Kaydedilecek bilgi çok kısa.")
    record = ctx.memory.add_fact(text, session_id=ctx.session_id, tags=(args.get("tags") or "")[:200])
    return {
        "saved": True,
        "id": record["id"],
        "text": record["text"],
        "already_existed": record.get("duplicate", False),
    }


async def memory_search(ctx: ToolContext, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    limit = max(1, min(int(args.get("limit") or 5), 10))
    found = ctx.memory.search_facts(query, session_id=ctx.session_id, limit=limit)
    return {"query": query, "count": len(found), "facts": [{"id": f["id"], "text": f["text"]} for f in found]}


# ============================================================ kayıt

def build_tools() -> dict[str, Tool]:
    """Tüm araçları isimle erişilebilir bir sözlük olarak döndürür."""
    tools = [
        Tool(
            name="get_weather",
            description=(
                "Bir şehrin anlık hava durumunu ve 3 günlük tahminini getirir. "
                "Kullanıcı hava durumunu, sıcaklığı, yağışı veya rüzgarı sorduğunda kullan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Şehir adı, örn. 'Antalya' veya 'Ankara'"},
                    "lat": {"type": "number", "description": "Enlem (koordinat biliniyorsa)"},
                    "lon": {"type": "number", "description": "Boylam (koordinat biliniyorsa)"},
                },
            },
            handler=get_weather,
            status_text="Hava durumuna bakıyorum",
        ),
        Tool(
            name="web_search",
            description=(
                "Güncel veya genel bilgi için Vikipedi ve DuckDuckGo üzerinden arama yapar. "
                "Kişi, yer, kavram, haber ve doğrulanması gereken bilgilerde kullan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Arama sorgusu"},
                    "limit": {"type": "integer", "description": "En fazla sonuç sayısı (1-6)"},
                },
                "required": ["query"],
            },
            handler=web_search,
            status_text="Web'de araştırıyorum",
        ),
        Tool(
            name="calculate",
            description=(
                "Matematiksel ifadeyi güvenli biçimde hesaplar. Desteklenen: + - * / // % **, "
                "parantez, sqrt/abs/round/floor/ceil/log/exp/sin/cos/tan/min/max, pi ve e sabitleri. "
                "Herhangi bir hesap sorusunda mutlaka bu aracı kullan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Hesaplanacak ifade, örn. '(25*4)/2 + sqrt(81)'"}
                },
                "required": ["expression"],
            },
            handler=_calculate_handler,
            status_text="Hesaplıyorum",
        ),
        Tool(
            name="current_datetime",
            description="Şu anki tarih, saat ve gün bilgisini verir. Tarih/saat sorularında kullan.",
            input_schema={
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA saat dilimi, varsayılan Europe/Istanbul"}
                },
            },
            handler=_datetime_handler,
            status_text="Saate bakıyorum",
        ),
        Tool(
            name="check_site",
            description=(
                "Bir web sitesinin çalışıp çalışmadığını, HTTP durumunu, yanıt süresini ve "
                "temel SEO/erişilebilirlik bilgilerini kontrol eder."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Kontrol edilecek adres, örn. 'ornek.com'"}},
                "required": ["url"],
            },
            handler=check_site,
            status_text="Siteyi kontrol ediyorum",
        ),
        Tool(
            name="memory_save",
            description=(
                "Kullanıcıyla ilgili kalıcı bir bilgiyi (ad, şehir, meslek, tercih, hatırlatma) kaydeder. "
                "Yalnızca kullanıcı hatırlanmasını istediğinde veya açıkça kişisel bilgi verdiğinde kullan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Kaydedilecek bilgi, tek cümle"},
                    "tags": {"type": "string", "description": "Virgülle ayrılmış etiketler (opsiyonel)"},
                },
                "required": ["text"],
            },
            handler=memory_save,
            status_text="Hafızaya kaydediyorum",
        ),
        Tool(
            name="memory_search",
            description="Kullanıcı hakkında daha önce kaydedilen bilgileri arar. 'Benim hakkımda ne biliyorsun' gibi sorularda kullan.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Aranacak konu; boş bırakılırsa son notlar döner"},
                    "limit": {"type": "integer"},
                },
            },
            handler=memory_search,
            status_text="Hafızama bakıyorum",
        ),
    ]
    return {tool.name: tool for tool in tools}


async def _calculate_handler(ctx: ToolContext, args: dict) -> dict:
    expression = args.get("expression") or ""
    value = safe_calculate(expression)
    return {"expression": expression, "value": value, "formatted": format_number(value)}


async def _datetime_handler(ctx: ToolContext, args: dict) -> dict:
    return current_datetime(ctx, args)


def tool_specs(tools: dict[str, Tool]) -> list[dict]:
    return [tool.spec() for tool in tools.values()]
