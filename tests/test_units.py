import datetime as dt

import pytest

from jev.models import Intent
from jev.questions import QuestionsError, load_questions, render_question
from jev.router import rule_route
from jev.weather import _within_window, hot_verdict

from .conftest import TODAY, make_settings


@pytest.mark.parametrize(
    "q,intent,loc",
    [
        ("What is the current temperature in Austin, TX on 2026-10-04?", Intent.CURRENT_TEMPERATURE, "Austin, TX"),
        ("What is the median temperature for Phoenix, AZ historically?", Intent.HISTORICAL_MEDIAN, "Phoenix, AZ"),
        ("Is it hot in New York, NY on 2026-10-04?", Intent.IS_HOT, "New York, NY"),
        ("Is it currently hot in Miami, FL for this time of the year?", Intent.IS_HOT, "Miami, FL"),
        ("Tell me a joke", Intent.UNKNOWN, None),
    ],
)
def test_rule_route(q, intent, loc):
    p = rule_route(q, TODAY)
    assert p.intent == intent
    assert p.location == loc


def test_rule_route_date():
    assert rule_route("Is it hot in Austin, TX on 2025-07-01?", TODAY).date == dt.date(2025, 7, 1)
    assert rule_route("Is it hot in Austin, TX today?", TODAY).date == TODAY


def test_render_question_brackets():
    out = render_question("Is it hot in [city/state] on [today]", "Austin, TX", TODAY)
    assert out == "Is it hot in Austin, TX on 2026-10-04"


def test_load_questions_yaml(tmp_path):
    f = tmp_path / "q.yaml"
    f.write_text("questions:\n  - A {location}\n  - B\n")
    qs, src = load_questions(make_settings(test_mode=False, questions_file=str(f)))
    assert qs == ["A {location}", "B"]


def test_load_questions_missing(tmp_path):
    with pytest.raises(QuestionsError):
        load_questions(make_settings(test_mode=False, questions_file=str(tmp_path / "nope.yaml")))


def test_repo_questions_file_is_valid():
    qs, _ = load_questions(make_settings(test_mode=False, questions_file="config/questions.yaml"))
    assert qs


def test_within_window_wraps_year_end():
    assert _within_window(dt.date(2020, 12, 30), dt.date(2026, 1, 2), 7)
    assert not _within_window(dt.date(2020, 6, 1), dt.date(2026, 1, 2), 7)
    assert _within_window(dt.date(2021, 2, 28), dt.date(2028, 2, 29), 0)


def test_hot_verdict_levels():
    s = {"median_high": 80, "p75_high": 85, "p90_high": 90}
    assert hot_verdict(91, s)["level"] == "very hot"
    assert hot_verdict(86, s)["is_hot"] is True
    assert hot_verdict(82, s)["level"] == "warmer than usual"
    assert hot_verdict(70, s) == {"is_hot": False, "level": "not hot", "anomaly_vs_median_high": -10}
