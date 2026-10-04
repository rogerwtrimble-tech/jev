from jev.config import TEST_QUESTIONS

from .conftest import make_jev, make_settings, _FrozenDate
from fastapi.testclient import TestClient
from jev.api import create_app


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["test_mode"] is True


def test_questions_in_test_mode(client):
    r = client.get("/questions").json()
    assert r["source"] == "test_mode"
    assert r["questions"] == TEST_QUESTIONS


def test_ask_default_question(client):
    r = client.post("/ask", json={"location": "Austin, TX"})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "Is it currently hot in Austin, TX for this time of the year?"
    assert body["intent"] == "is_hot"
    assert body["facts"]["location"] == "Austin, Texas, US"  # picked TX over GA
    assert body["facts"]["verdict"]["is_hot"] is True  # 93 > p75 of 80..89
    assert body["answer"].startswith("Yes")
    assert body["answered_by"] == "template"


def test_ask_empty_body_uses_defaults(client):
    body = client.post("/ask").json()
    assert body["location"] == "Austin, TX"
    assert body["intent"] == "is_hot"


def test_ask_get(client):
    body = client.get("/ask", params={"location": "Austin, TX"}).json()
    assert body["intent"] == "is_hot"


def test_batch_runs_three_test_questions(client):
    body = client.post("/ask/batch", json={"location": "Austin, TX"}).json()
    assert [r["intent"] for r in body["results"]] == ["current_temperature", "historical_median", "is_hot"]
    cur, hist, hot = body["results"]
    assert "91.0°F" in cur["answer"]
    assert hist["facts"]["historical"]["median_high"] == 84.5
    assert hot["date"] == "2026-10-04"


def test_batch_uses_questions_file_when_not_test_mode(tmp_path, monkeypatch):
    qfile = tmp_path / "q.txt"
    qfile.write_text("# comment\nWhat is the median temperature for {location}?\n")
    settings = make_settings(test_mode=False, questions_file=str(qfile))
    monkeypatch.setattr("jev.pipeline.dt.date", _FrozenDate)
    with TestClient(create_app(settings, make_jev(settings))) as c:
        assert c.get("/questions").json()["questions"] == ["What is the median temperature for {location}?"]
        body = c.post("/ask/batch", json={"location": "Austin, TX"}).json()
    assert len(body["results"]) == 1
    assert body["results"][0]["intent"] == "historical_median"


def test_unknown_question(client):
    body = client.post("/ask", json={"question": "Will it rain in Austin, TX?"}).json()
    assert body["intent"] == "unknown"
    assert "Sorry" in body["answer"]


def test_slm_and_llm_path(monkeypatch):
    settings = make_settings(slm_url="http://slm:11434", llm_provider="anthropic", llm_api_key="k")
    monkeypatch.setattr("jev.pipeline.dt.date", _FrozenDate)
    with TestClient(create_app(settings, make_jev(settings))) as c:
        body = c.post("/ask", json={"location": "Austin, TX"}).json()
    assert body["router"] == "slm"
    assert body["answer"] == "LLM says hot."
    assert body["answered_by"].startswith("anthropic:")


def test_llm_missing_key_falls_back_to_template(monkeypatch):
    settings = make_settings(llm_provider="openai", llm_api_key="")
    monkeypatch.setattr("jev.pipeline.dt.date", _FrozenDate)
    with TestClient(create_app(settings, make_jev(settings))) as c:
        body = c.post("/ask", json={"location": "Austin, TX"}).json()
    assert body["answered_by"] == "template"
    assert body["facts"]["warnings"]
