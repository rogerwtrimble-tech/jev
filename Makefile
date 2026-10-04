VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install env run test docker ask batch

install:            ## Create venv and install Jev + dev deps
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e ".[dev]"

env:                ## Create .env from the template (won't overwrite)
	@test -f .env || cp .env.example .env && echo ".env ready"

run:                ## Run the API with auto-reload on http://localhost:8000
	$(PY) -m jev serve --reload

test:               ## Run the test suite (offline, all external calls mocked)
	$(PY) -m pytest -q

ask:                ## Ask the default question: make ask LOCATION="Austin, TX"
	$(PY) -m jev ask --location "$(or $(LOCATION),Austin, TX)"

batch:              ## Run all configured questions: make batch LOCATION="Austin, TX"
	$(PY) -m jev batch --location "$(or $(LOCATION),Austin, TX)"

docker:             ## Build and run with Docker Compose
	docker compose up --build
