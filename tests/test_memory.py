"""SQLite hafıza deposu testleri."""

from __future__ import annotations

from pathlib import Path

from nova.memory import MemoryStore


def test_add_and_list_facts(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    first = store.add_fact("Adım Cem", session_id="s1", tags="kimlik")
    second = store.add_fact("Antalya'da yaşıyorum", session_id="s1")
    assert first["id"] and second["id"]
    facts = store.list_facts("s1")
    assert [fact["text"] for fact in facts] == ["Antalya'da yaşıyorum", "Adım Cem"]


def test_duplicate_fact_is_not_inserted_twice(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    first = store.add_fact("Kahveyi sade içerim")
    second = store.add_fact("kahveyi sade içerim")
    assert second["duplicate"] is True
    assert first["id"] == second["id"]
    assert len(store.list_facts()) == 1


def test_search_facts_scores_keyword_overlap(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    store.add_fact("Köpeğimin adı Pamuk")
    store.add_fact("Doğum günüm 12 Mayıs")
    results = store.search_facts("köpeğimin adı neydi")
    assert results and results[0]["text"] == "Köpeğimin adı Pamuk"


def test_search_facts_returns_recent_for_general_question(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    store.add_fact("Adım Cem")
    results = store.search_facts("benim hakkımda ne biliyorsun")
    assert len(results) == 1


def test_delete_and_clear(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    fact = store.add_fact("Silinecek not")
    assert store.delete_fact(fact["id"]) is True
    assert store.delete_fact(fact["id"]) is False
    store.add_fact("Bir")
    store.add_fact("İki")
    assert store.clear_facts() == 2


def test_messages_roundtrip_and_limit(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    for index in range(5):
        store.append_message("s1", "user", f"soru {index}")
        store.append_message("s1", "assistant", f"yanıt {index}")
    recent = store.recent_messages("s1", limit=4)
    assert [item["content"] for item in recent] == ["soru 3", "yanıt 3", "soru 4", "yanıt 4"]
    assert store.stats()["messages"] == 10
    assert store.stats()["sessions"] == 1
    assert store.clear_session("s1") == 10
    assert store.recent_messages("s1") == []


def test_in_memory_store_keeps_data():
    store = MemoryStore(":memory:")
    store.add_fact("bellek içi")
    assert store.list_facts()[0]["text"] == "bellek içi"
