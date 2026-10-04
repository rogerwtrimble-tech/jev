"""Loading and rendering of the question list."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml

from jev.config import TEST_QUESTIONS, Settings


class QuestionsError(RuntimeError):
    pass


def load_questions(settings: Settings) -> tuple[list[str], str]:
    """Return (questions, source). In test mode the built-in questions are always used."""
    if settings.test_mode:
        return list(TEST_QUESTIONS), "test_mode"

    path = Path(settings.questions_file)
    if not path.is_file():
        raise QuestionsError(f"QUESTIONS_FILE not found: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:  # plain text: one question per line, '#' comments allowed
        data = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]

    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list) or not all(isinstance(q, str) and q.strip() for q in data) or not data:
        raise QuestionsError(f"{path} must contain a non-empty list of question strings")
    return [q.strip() for q in data], str(path)


def render_question(template: str, location: str | None, date: dt.date) -> str:
    """Fill {location}/{date} placeholders (also accepts [City/State]-style brackets)."""
    loc = location or "{location}"
    out = template
    for token in ("[City/State]", "[city/state]", "City/State"):
        out = out.replace(token, loc)
    for token in ("[today]", "[Today]", "[date]"):
        out = out.replace(token, date.isoformat())
    return out.replace("{location}", loc).replace("{date}", date.isoformat())
