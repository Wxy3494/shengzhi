import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.games import router as games_router
from .api.health import router as health_router
from .config import settings
from .llm.base import build_adapter
from .services.game_service import GameService
from .storage.sqlite import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.database_path)
    adapter = build_adapter(settings)
    app.state.db = db
    app.state.game_service = GameService(db, adapter)
    app.state.llm_mode = settings.llm_mode
    yield
    db.close()


app = FastAPI(title="圣旨输入中 API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(games_router)
