"""Ajan döngüsü testleri: araç çağrıları, hafıza, hata yolları."""

from __future__ import annotations

import asyncio

from nova.agent import NovaAgent
from nova.llm import AssistantTurn, ProviderError, ToolCall


class ScriptedProvider:
    """Önceden yazılmış turları sırayla döndüren sahte sağlayıcı."""

    name = "scripted"
    model = "test-model"

    def __init__(self, turns, fail: bool = False):
        self.turns = list(turns)
        self.fail = fail
        self.tool_counts: list[int] = []
        self.seen_messages: list[list[dict]] = []

    async def stream_turn(self, system, messages, tools):
        self.tool_counts.append(len(tools))
        self.seen_messages.append(list(messages))
        if self.fail:
            raise ProviderError("Model servisi kapalı")
        turn = self.turns.pop(0) if self.turns else AssistantTurn(text="Peki.", stop_reason="end_turn")
        if turn.text:
            yield {"type": "delta", "text": turn.text}
        yield {"type": "turn", "turn": turn}

    async def complete(self, system, user, *, max_tokens: int = 1200) -> str:
        return "inceleme tamam"


def _collect(agent: NovaAgent, question: str, **kwargs) -> list[dict]:
    async def run():
        return [event async for event in agent.stream(question, **kwargs)]

    return asyncio.run(run())


def test_offline_answer_uses_calculate_tool(agent: NovaAgent):
    result = asyncio.run(agent.answer("25 kere 4 kaç eder?"))
    assert "100" in result.answer
    assert result.tools_used[0]["name"] == "calculate"
    assert result.tools_used[0]["ok"] is True


def test_stream_emits_start_tool_events_and_done(agent: NovaAgent):
    events = _collect(agent, "Antalya'da hava nasıl?")
    types = [event["type"] for event in events]
    assert types[0] == "start"
    assert "tool_start" in types and "tool_result" in types
    assert types[-1] == "done"
    done = events[-1]
    assert done["answer"]
    assert any(tool["name"] == "get_weather" for tool in done["tools_used"])


def test_web_search_collects_sources(agent: NovaAgent):
    result = asyncio.run(agent.answer("İstanbul'un fethi nedir?"))
    assert result.sources
    assert result.sources[0]["url"].startswith("https://")
    assert "1453" in result.answer


def test_memory_is_shared_between_questions(agent: NovaAgent):
    first = asyncio.run(agent.answer("Benim adım Cem, bunu hatırla", session_id="oturum"))
    assert "kaydettim" in first.answer.lower()
    second = asyncio.run(agent.answer("Benim hakkımda ne biliyorsun?", session_id="oturum"))
    assert "Cem" in second.answer


def test_unknown_tool_is_reported_not_crashing(settings, memory, tools):
    provider = ScriptedProvider(
        [
            AssistantTurn(
                text="",
                tool_calls=[ToolCall(id="c1", name="uydurma_arac", arguments={})],
                stop_reason="tool_use",
            )
        ]
    )
    agent = NovaAgent(provider, memory, settings, tools)
    events = _collect(agent, "şunu yap")
    tool_events = [event for event in events if event["type"] == "tool_result"]
    assert tool_events and tool_events[0]["ok"] is False
    assert any(event["type"] == "done" for event in events)


def test_provider_failure_returns_graceful_answer(settings, memory, tools):
    agent = NovaAgent(ScriptedProvider([], fail=True), memory, settings, tools)
    events = _collect(agent, "merhaba dünya")
    assert any(event["type"] == "error" for event in events)
    done = events[-1]
    assert done["type"] == "done"
    assert done["answer"]  # kullanıcıya yine de bir metin döner


def test_tool_round_limit_is_enforced(settings, memory, tools):
    settings = settings.__class__(**{**settings.__dict__, "max_tool_rounds": 2})
    looping = AssistantTurn(
        text="",
        tool_calls=[ToolCall(id="c", name="calculate", arguments={"expression": "1+1"})],
        stop_reason="tool_use",
    )
    provider = ScriptedProvider([looping, looping, looping, looping])
    agent = NovaAgent(provider, memory, settings, tools)
    result = asyncio.run(agent.answer("hesapla"))
    assert len(result.tools_used) == 2  # iki turdan fazlası çalıştırılmaz
    assert provider.tool_counts[-1] == 0  # son tur araçsız istenir


def test_history_is_passed_to_provider(settings, memory, tools):
    provider = ScriptedProvider([])
    agent = NovaAgent(provider, memory, settings, tools)
    asyncio.run(
        agent.answer(
            "devam et",
            history=[{"who": "user", "text": "önceki soru"}, {"who": "bot", "text": "önceki yanıt"}],
        )
    )
    texts = [message.get("text") for message in provider.seen_messages[0]]
    assert "önceki soru" in texts and "önceki yanıt" in texts


def test_empty_question_yields_error_event(agent: NovaAgent):
    events = _collect(agent, "   ")
    assert events[0]["type"] == "error"


def test_review_code_uses_provider(settings, memory, tools):
    provider = ScriptedProvider([])
    agent = NovaAgent(provider, memory, settings, tools)
    assert asyncio.run(agent.review_code("print(1)", "a.py")) == "inceleme tamam"
