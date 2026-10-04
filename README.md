# Jev

A FastAPI service that answers weather questions about a **City/State**.

- **SLM** (small language model) reads the question and works out what it asks for (intent, location, date).
- **Open-Meteo** supplies the weather data: live conditions plus 30 years of history. It is free and needs no key.
- **LLM** (large language model) writes the final answer using only the retrieved facts.

The default question is:

> **Is it currently hot in [City/State] for this time of the year?**

```
question ──► SLM router ──► intent + location + date
                               │
                               ▼
                     Open-Meteo (geocode, current, 30-yr history)
                               │  facts (JSON)
                               ▼
                    LLM provider ──► natural-language answer
```

Each stage has a fallback, so a fresh clone runs with no configuration. Without an SLM it uses a rule-based router. Without an LLM it uses a built-in answer template.

---

## Quick start

```bash
git clone <this repo> && cd jev
make install          # venv + deps
make env              # creates .env from .env.example
make run              # http://localhost:8000/docs
```

```bash
curl -X POST localhost:8000/ask -H 'content-type: application/json' -d '{"location":"Austin, TX"}'
```

```json
{
  "question": "Is it currently hot in Austin, TX for this time of the year?",
  "answer": "Yes — Austin, Texas, US is hot for this time of year. The high on 2026-10-04 is 93.0°F vs. a historical median high of 84.5°F (+8.5°F); hot threshold (75th percentile) is 86.8°F.",
  "intent": "is_hot",
  "facts": { "...": "..." },
  "router": "rules",
  "answered_by": "template"
}
```

Or use Docker: `make env && docker compose up --build`.

---

## The only 3 things you need to provide

Set them in `.env`:

| # | What | Setting(s) | Notes |
|---|------|------------|-------|
| 1 | **Your list of questions** | `QUESTIONS_FILE` (default `config/questions.yaml`), `TEST_MODE=false` | YAML/JSON list or `.txt` (one per line). Placeholders: `{location}`, `{date}`. `[City/State]` and `[today]` also work. |
| 2 | **SLM URL** | `SLM_URL`, `SLM_MODEL`, optional `SLM_API_KEY` | Any OpenAI-compatible `/v1/chat/completions` server: Ollama, vLLM, llama.cpp, LM Studio, TGI. `http://host:11434`, `.../v1` and full `.../chat/completions` URLs all work. |
| 3 | **LLM provider + key** | `LLM_PROVIDER`, `LLM_API_KEY`, optional `LLM_MODEL` / `LLM_BASE_URL` | `openai`, `anthropic`, or `openai_compatible` (any gateway at `LLM_BASE_URL`). `none` = template answers. |

Example:

```dotenv
TEST_MODE=false
QUESTIONS_FILE=config/questions.yaml
SLM_URL=http://localhost:11434
SLM_MODEL=phi3:mini
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
```

### Test mode

With `TEST_MODE=true` (the default), Jev ignores `QUESTIONS_FILE` and uses these 3 built-in questions:

1. What is the current temperature in `{location}` on `{date}`?
2. What is the median temperature for `{location}` historically?
3. Is it hot in `{location}` on `{date}`?

Run them all with `POST /ask/batch` or `make batch LOCATION="Phoenix, AZ"`.

---

## API

| Method | Path | Body / Query | Description |
|--------|------|--------------|-------------|
| `GET` | `/health` | – | Status, test mode, SLM/LLM configuration |
| `GET` | `/questions` | – | The active question list (test or file) |
| `POST` | `/ask` | `{"question"?, "location"?, "date"?}` | Ask one question. Empty body = default question for `DEFAULT_LOCATION` |
| `GET` | `/ask` | `?location=Austin, TX&question=...` | Browser-friendly `/ask` |
| `POST` | `/ask/batch` | `{"location"?, "date"?}` | Run every active question for a location |

Interactive docs are at `/docs`.

Each response includes `facts` (the raw numbers), `router` (`slm` or `rules`) and `answered_by` (`provider:model` or `template`), so you can see how every answer was produced.

### How "hot for this time of year" is decided

- Jev takes the daily highs within ±`HISTORY_WINDOW_DAYS` (default 7) of today's calendar date, across the last `HISTORY_YEARS` (default 30) years.
- Today's forecast high is compared against that distribution:
  - ≥ 90th percentile → **very hot**
  - ≥ 75th percentile → **hot** (`is_hot: true`)
  - ≥ median → **warmer than usual**
  - otherwise → **not hot**

Other questions:

- "Current temperature" uses live conditions for today, the archive for past dates, and the forecast for up to 16 days ahead.
- "Median temperature" reports the median high, mean and low for this time of year.

---

## CLI

```bash
python -m jev serve --port 8000
python -m jev ask --location "Miami, FL"                       # default question
python -m jev ask "What is the median temperature for Denver, CO historically?"
python -m jev batch --location "Phoenix, AZ"
```

## Configuration reference

See [`.env.example`](.env.example). Other settings:

- `DEFAULT_QUESTION`, `DEFAULT_LOCATION`
- `TEMPERATURE_UNIT` (`fahrenheit` | `celsius`)
- `HISTORY_YEARS`, `HISTORY_WINDOW_DAYS`
- Timeouts

## Project layout

```
src/jev/
  api.py        FastAPI app (create_app factory)
  pipeline.py   Orchestrates route → facts → answer; template fallback answers
  router.py     SLM router (OpenAI-compatible) + rule-based fallback
  llm.py        LLM providers: openai, anthropic, openai_compatible, none
  weather.py    Open-Meteo client: geocoding (US state abbrevs), current, history, hot verdict
  questions.py  Question list loading (YAML/JSON/TXT) and placeholder rendering
  config.py     Settings (env / .env) and the 3 TEST_MODE questions
config/questions.yaml   Your questions (used when TEST_MODE=false)
tests/                  Offline tests; all HTTP is mocked
```

## Tests

```bash
make test
```

The tests mock Open-Meteo, the SLM and the LLM with `httpx.MockTransport`, so they need no network or keys.
