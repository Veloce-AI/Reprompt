from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reprompt_api.auth import router as auth_router
from reprompt_api.db import engine
from reprompt_api.migrations import router as migrations_router
from reprompt_api.model_cards import router as model_cards_router
from reprompt_api.models import Base
from reprompt_api.pipelines import router as pipelines_router
from reprompt_api.rubrics import router as rubrics_router
from reprompt_api.settings import router as settings_router
from reprompt_api.stage_records import router as stage_records_router
from reprompt_api.trace_format import router as trace_format_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Dev convenience only: for SQLite this creates tables if they don't
    # already exist (idempotent, no-op once Alembic-managed). Production
    # (Postgres) deployments should rely on `alembic upgrade head` instead.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Reprompt API", version="0.0.1", lifespan=lifespan)

# Local dev only: Vite serves the web app from :5173, the API from :8000.
# Tighten/replace this with real origin config before deploying anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router)
app.include_router(rubrics_router)
app.include_router(migrations_router)
app.include_router(model_cards_router)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(stage_records_router)
app.include_router(trace_format_router)


@app.get("/health")
def health():
    return {"status": "ok"}
