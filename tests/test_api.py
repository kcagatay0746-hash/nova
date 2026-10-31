"""HTTP arayüzü testleri (FastAPI TestClient, ağsız)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nova.safety import RateLimiter


def test_health_reports_mode_and_memory(client: TestClient):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "demo"
    assert payload["provider"] == "offline"
    assert "facts" in payload["memory"]


def test_tools_endpoint_lists_schemas(client: TestClient):
    tools = client.get("/api/tools").json()["tools"]
    names = {tool["name"] for tool in tools}
    assert {"get_weather", "calculate", "memory_save"} <= names


def test_index_is_served(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Nova" in response.text
    assert "/app.js" not in response.text or "app.js" in response.text


def test_ask_answers_math_with_tool(client: TestClient):
    payload = client.post("/api/ask", json={"question": "25 kere 4 kaç eder?", "session_id": "api"}).json()
    assert "100" in payload["answer"]
    assert payload["tools_used"][0]["name"] == "calculate"


def test_ask_accepts_legacy_history_format(client: TestClient):
    payload = client.post(
        "/api/ask",
        json={
            "question": "peki 2 çarpı 3 kaç eder?",
            "history": [{"who": "user", "text": "merhaba"}, {"who": "bot", "text": "selam"}],
        },
    ).json()
    assert "6" in payload["answer"]


def test_ask_with_empty_question_is_graceful(client: TestClient):
    payload = client.post("/api/ask", json={"question": "  "}).json()
    assert payload["answer"]


def test_chat_stream_returns_sse_with_done_event(client: TestClient):
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"question": "12 çarpı 12 kaç eder?", "session_id": "sse"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    events = [
        json.loads(line[5:].strip())
        for line in body.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert any(event["type"] == "delta" for event in events)


def test_chat_stream_get_variant(client: TestClient):
    with client.stream("GET", "/api/chat/stream", params={"q": "saat kaç", "session_id": "g"}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "done" in body


def test_memory_crud(client: TestClient):
    created = client.post("/api/memory", json={"text": "En sevdiğim renk turkuaz", "session_id": "m"})
    assert created.status_code == 200
    fact_id = created.json()["fact"]["id"]

    listed = client.get("/api/memory", params={"session_id": "m"}).json()
    assert len(listed["facts"]) == 1

    deleted = client.delete("/api/memory", params={"fact_id": fact_id}).json()
    assert deleted["deleted"] is True
    assert client.get("/api/memory", params={"session_id": "m"}).json()["facts"] == []


def test_memory_rejects_too_short_text(client: TestClient):
    response = client.post("/api/memory", json={"text": "ab", "session_id": "m"})
    assert response.status_code == 400


def test_site_check_maps_tool_result(client: TestClient):
    payload = client.post("/api/site-check", json={"url": "example.com", "analyse": False}).json()
    assert payload["up"] is True
    assert payload["status"] == 200
    assert payload["responseTime"] == 42
    assert payload["title"] == "Example Domain"


def test_review_returns_text(client: TestClient):
    payload = client.post("/api/review", json={"code": "def f():\n    return 1\n", "filename": "a.py"}).json()
    assert payload["review"]
    assert "satır" in payload["review"].lower()


def test_review_empty_code(client: TestClient):
    payload = client.post("/api/review", json={"code": ""}).json()
    assert payload["review"] is None
    assert payload["error"]


def test_rate_limit_returns_429(monkeypatch, client: TestClient):
    import server

    monkeypatch.setattr(server, "limiter", RateLimiter(1))
    assert client.get("/api/health").status_code == 200
    second = client.get("/api/health")
    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_private_files_are_not_served(client: TestClient):
    for path in ("/server.py", "/nova/agent.py", "/.env.example", "/nova.db", "/README.md"):
        assert client.get(path).status_code == 404, path


def test_static_assets_are_served(client: TestClient):
    for path in ("/index.html", "/app.js", "/styles.css"):
        assert client.get(path).status_code == 200, path
