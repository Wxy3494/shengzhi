from dataclasses import dataclass, field
from typing import Any, Protocol

from .schema import Candidate


class ModelOutputInvalid(Exception):
    """模型输出解析或校验失败(含一次修复后仍失败)。"""


class ModelTimeout(Exception):
    """模型调用超时。"""


class ModelUnavailable(Exception):
    """模型服务不可达或配置缺失。"""


@dataclass
class ModelContext:
    game: dict
    turn_no: int
    period: str
    history: list[dict] = field(default_factory=list)
    due_echoes: list[dict] = field(default_factory=list)
    player_policy: str = ""
    deadline: float | None = None


class LlmAdapter(Protocol):
    def evaluate(self, context: ModelContext) -> Candidate: ...


def build_live_adapter(settings: Any) -> LlmAdapter:
    from .live import LiveAdapter

    return LiveAdapter(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def build_fixture_adapter() -> LlmAdapter:
    from .fixture import FixtureAdapter

    return FixtureAdapter()


def build_adapter(settings: Any) -> LlmAdapter:
    if settings.llm_mode == "live":
        missing = []
        if not settings.llm_base_url:
            missing.append("LLM_BASE_URL")
        if not settings.llm_api_key:
            missing.append("LLM_API_KEY")
        if not settings.llm_model:
            missing.append("LLM_MODEL")
        if missing:
            raise RuntimeError(
                f"LLM_MODE=live 但缺少配置: {', '.join(missing)}。"
                "请在 backend/.env 中补齐,或改回 LLM_MODE=fixture。"
            )
        return build_live_adapter(settings)
    if settings.llm_mode == "fixture":
        return build_fixture_adapter()
    raise RuntimeError(f"未知 LLM_MODE: {settings.llm_mode!r},拒绝启动。")
