"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from jev import __version__
from jev.config import Settings, get_settings
from jev.models import AskRequest, AskResponse, BatchRequest, BatchResponse, HealthResponse, QuestionsResponse
from jev.pipeline import Jev
from jev.questions import QuestionsError, load_questions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, jev: Jev | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.jev = jev or Jev.from_settings(settings)
        yield
        await app.state.jev.aclose()

    app = FastAPI(
        title="Jev",
        version=__version__,
        description="Ask weather questions. Default: "
        "'Is it currently hot in [City/State] for this time of the year?'",
        lifespan=lifespan,
    )

    def get_jev(request: Request) -> Jev:
        return request.app.state.jev

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            test_mode=settings.test_mode,
            slm_configured=settings.slm_enabled,
            llm_provider=settings.llm_provider,
        )

    @app.get("/questions", response_model=QuestionsResponse, tags=["questions"])
    async def questions() -> QuestionsResponse:
        try:
            qs, source = load_questions(settings)
        except QuestionsError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return QuestionsResponse(test_mode=settings.test_mode, source=source, questions=qs)

    @app.post("/ask", response_model=AskResponse, tags=["ask"])
    async def ask(body: AskRequest | None = None, jev: Jev = Depends(get_jev)) -> AskResponse:
        """Ask one question. With an empty body, asks the default question for DEFAULT_LOCATION."""
        body = body or AskRequest()
        return await jev.ask(body.question, body.location, body.date)

    @app.get("/ask", response_model=AskResponse, tags=["ask"])
    async def ask_get(
        location: str | None = Query(default=None, examples=["Austin, TX"]),
        question: str | None = Query(default=None),
        jev: Jev = Depends(get_jev),
    ) -> AskResponse:
        """Browser-friendly: GET /ask?location=Austin,%20TX"""
        return await jev.ask(question, location, None)

    @app.post("/ask/batch", response_model=BatchResponse, tags=["ask"])
    async def ask_batch(body: BatchRequest | None = None, jev: Jev = Depends(get_jev)) -> BatchResponse:
        """Run every configured question (or the 3 test questions in TEST_MODE) for a location."""
        body = body or BatchRequest()
        try:
            qs, _ = load_questions(settings)
        except QuestionsError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        location = body.location or settings.default_location
        results = [await jev.ask(q, location, body.date) for q in qs]
        return BatchResponse(
            test_mode=settings.test_mode,
            location=location,
            date=results[0].date if results else body.date,
            results=results,
        )

    return app


app = create_app()
