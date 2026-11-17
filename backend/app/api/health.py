from fastapi import APIRouter

from ..config import settings
from ..domain.models import ENGINE_VERSION, TOTAL_YEARS, YEARS_PER_TURN, period_name

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "game": "圣旨输入中……",
        "dynasty": "大晟朝",
        "period": period_name(1),
        "years_per_turn": YEARS_PER_TURN,
        "total_years": TOTAL_YEARS,
        "llm_mode": settings.llm_mode,
    }
