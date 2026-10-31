"""Araç kayıt defteri ve araç davranış testleri."""

from __future__ import annotations

import asyncio

import pytest

from nova.memory import MemoryStore
from nova.safety import SafetyError
from nova.tools import ToolContext, ToolError, build_tools, tool_specs


@pytest.fixture()
def ctx(settings, memory: MemoryStore) -> ToolContext:
    return ToolContext(memory=memory, settings=settings, session_id="test")


def test_registry_contains_expected_tools():
    tools = build_tools()
    assert {
        "get_weather",
        "web_search",
        "calculate",
        "current_datetime",
        "check_site",
        "memory_save",
        "memory_search",
    } <= set(tools)


def test_tool_specs_are_valid_json_schema():
    specs = tool_specs(build_tools())
    for spec in specs:
        assert spec["name"] and spec["description"]
        assert spec["input_schema"]["type"] == "object"
        assert "properties" in spec["input_schema"]


def test_calculate_handler(ctx: ToolContext):
    tools = build_tools()
    result = asyncio.run(tools["calculate"].handler(ctx, {"expression": "25*4"}))
    assert result["value"] == 100.0
    assert result["formatted"] == "100"


def test_datetime_handler_returns_turkish_fields(ctx: ToolContext):
    tools = build_tools()
    result = asyncio.run(tools["current_datetime"].handler(ctx, {}))
    assert result["timezone"] == "Europe/Istanbul"
    assert result["weekday"] in {
        "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"
    }
    assert result["spoken"]


def test_memory_save_and_search_roundtrip(ctx: ToolContext):
    tools = build_tools()
    saved = asyncio.run(tools["memory_save"].handler(ctx, {"text": "Kedimin adı Mırmır"}))
    assert saved["saved"] is True
    found = asyncio.run(tools["memory_search"].handler(ctx, {"query": "kedimin adı"}))
    assert found["count"] == 1
    assert "Mırmır" in found["facts"][0]["text"]


def test_memory_save_rejects_too_short(ctx: ToolContext):
    tools = build_tools()
    with pytest.raises(ToolError):
        asyncio.run(tools["memory_save"].handler(ctx, {"text": "ab"}))


def test_check_site_blocks_private_addresses(ctx: ToolContext):
    tools = build_tools()
    with pytest.raises(SafetyError):
        asyncio.run(tools["check_site"].handler(ctx, {"url": "http://localhost:8080"}))


@pytest.mark.parametrize("code,expected", [(0, "açık"), (61, "hafif yağmurlu"), (95, "gök gürültülü fırtına")])
def test_weather_text_turkish(code, expected):
    from nova.tools import weather_text

    assert weather_text(code) == expected


def test_parse_html_meta_handles_quoted_and_unquoted_attributes():
    from nova.tools import parse_html_meta

    quoted = '''<html lang="tr"><head><title> Nova  Test </title>
    <meta name="description" content="Türkçe açıklama"></head>
    <body><h1>Başlık</h1><h1>İkinci</h1></body></html>'''
    meta = parse_html_meta(quoted)
    assert meta["title"] == "Nova Test"
    assert meta["description"] == "Türkçe açıklama"
    assert meta["lang"] == "tr"
    assert meta["h1_count"] == 2

    unquoted = "<html lang=en><head><title>x</title></head><body><p>y</p></body></html>"
    meta2 = parse_html_meta(unquoted)
    assert meta2["lang"] == "en"
    assert meta2["description"] is None
    assert meta2["h1_count"] == 0
