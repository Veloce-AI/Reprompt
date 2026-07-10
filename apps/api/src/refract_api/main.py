from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from refract_api.db import engine
from refract_api.models import Base
from refract_api.pipelines import router as pipelines_router
from refract_api.rubrics import router as rubrics_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Dev convenience only: for SQLite this creates tables if they don't
    # already exist (idempotent, no-op once Alembic-managed). Production
    # (Postgres) deployments should rely on `alembic upgrade head` instead.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Refract API", version="0.0.1", lifespan=lifespan)

# Local dev only: Vite serves the web app from :5173, the API from :8000.
# Tighten/replace this with real origin config before deploying anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router)
app.include_router(rubrics_router)


@app.get("/health")
def health():
    return {"status": "ok"}
