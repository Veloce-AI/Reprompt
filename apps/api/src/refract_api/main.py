from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from refract_api.db import engine
from refract_api.models import Base
from refract_api.pipelines import router as pipelines_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Dev convenience only: for SQLite this creates tables if they don't
    # already exist (idempotent, no-op once Alembic-managed). Production
    # (Postgres) deployments should rely on `alembic upgrade head` instead.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Refract API", version="0.0.1", lifespan=lifespan)
app.include_router(pipelines_router)


@app.get("/health")
def health():
    return {"status": "ok"}
