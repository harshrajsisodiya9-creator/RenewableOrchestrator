from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.database import Base, engine
from api.routes import assets, factories, grids, projects


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Renewable Energy API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(projects.router)
app.include_router(assets.router)
app.include_router(factories.router)
app.include_router(grids.router)


@app.get("/health")
def health():
    return {"status": "ok"}
