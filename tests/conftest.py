"""Test yapılandırması: tüm testler ağsız (hermetik) çalışır.

Ağa çıkan araçlar (hava durumu, web araması, site kontrolü) sahte handler'larla
değiştirilir; hesaplama, tarih ve hafıza araçları gerçek kodla çalışır.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nova.agent import NovaAgent
from nova.config import Settings
from nova.llm import OfflineProvider
from nova.memory import MemoryStore
from nova.safety import RateLimiter
from nova.tools import Tool, build_tools


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        provider="offline",
        model="nova-local-v2",
        memory_db=tmp_path / "nova-test.db",
        rate_limit_per_minute=0,
        max_tool_rounds=4,
        ca_bundle=None,
    )


@pytest.fixture()
def memory(settings: Settings) -> MemoryStore:
    return MemoryStore(settings.memory_db)


async def _fake_weather(ctx, args):
    return {
        "place": "Antalya, Türkiye",
        "temperature": 24,
        "feels_like": 26,
        "humidity": 61,
        "wind_kmh": 12,
        "condition": "az bulutlu",
        "is_day": True,
        "forecast": [
            {"date": "2026-11-01", "condition": "yağmurlu", "max": 21, "min": 14, "precipitation_chance": 70}
        ],
        "source": "Open-Meteo",
    }


async def _fake_search(ctx, args):
    return {
        "query": args.get("query", ""),
        "results": [
            {
                "title": "İstanbul'un Fethi",
                "snippet": "İstanbul 1453 yılında II. Mehmed tarafından fethedildi.",
                "url": "https://tr.wikipedia.org/?curid=1234",
                "source": "Vikipedi (tr)",
            }
        ],
    }


async def _fake_site(ctx, args):
    return {
        "url": "https://example.com/",
        "up": True,
        "status": 200,
        "response_ms": 42,
        "size_kb": 1.2,
        "https": True,
        "title": "Example Domain",
        "description": "Örnek açıklama",
        "lang": "en",
        "h1_count": 1,
        "server": "ECS",
    }


STUBS = {"get_weather": _fake_weather, "web_search": _fake_search, "check_site": _fake_site}


@pytest.fixture()
def tools() -> dict[str, Tool]:
    registry = build_tools()
    for name, handler in STUBS.items():
        original = registry[name]
        registry[name] = Tool(
            name=original.name,
            description=original.description,
            input_schema=original.input_schema,
            handler=handler,
            status_text=original.status_text,
        )
    return registry


@pytest.fixture()
def agent(settings: Settings, memory: MemoryStore, tools: dict[str, Tool]) -> NovaAgent:
    return NovaAgent(provider=OfflineProvider(settings), memory=memory, settings=settings, tools=tools)


@pytest.fixture()
def client(settings: Settings, memory: MemoryStore, tools: dict[str, Tool]) -> TestClient:
    import server

    server.settings = settings
    server.memory = memory
    server.agent = NovaAgent(provider=OfflineProvider(settings), memory=memory, settings=settings, tools=tools)
    server.limiter = RateLimiter(0)
    return TestClient(server.app)
