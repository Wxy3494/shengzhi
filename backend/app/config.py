import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

VALID_MODES = {"live", "fixture"}


class Settings:
    def __init__(self) -> None:
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "").strip()
        self.llm_api_key = os.environ.get("LLM_API_KEY", "").strip()
        self.llm_model = os.environ.get("LLM_MODEL", "").strip()
        raw_mode = os.environ.get("LLM_MODE", "fixture").strip().lower()
        if raw_mode not in VALID_MODES:
            raise ValueError(f"LLM_MODE 必须为 live 或 fixture,当前值: {raw_mode!r}")
        self.llm_mode = raw_mode
        self.database_path = os.environ.get(
            "DATABASE_PATH",
            str(BACKEND_DIR / "data" / "shengzhi.db"),
        )
        self.llm_timeout_seconds = 50.0
        self.cors_origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        self.cors_origins.extend(
            origin.strip().rstrip("/")
            for origin in os.environ.get("CORS_ORIGINS", "").split(",")
            if origin.strip()
        )


settings = Settings()
