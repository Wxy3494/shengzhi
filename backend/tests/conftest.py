import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.llm.base import LlmAdapter, ModelContext
from app.llm.fixture import FixtureAdapter
from app.llm.schema import AcceptedCandidate
from app.services.game_service import GameService
from app.storage.sqlite import Database


class ScriptedAdapter(LlmAdapter):
    """按脚本返回候选或异常,记录每次调用的上下文。"""

    def __init__(self, responses=None, default=None):
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[ModelContext] = []

    def evaluate(self, context: ModelContext):
        self.calls.append(context)
        if self.responses:
            item = self.responses.pop(0)
        elif self.default is not None:
            item = self.default
        else:
            raise AssertionError("脚本适配器没有可用响应")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(context)
        return item


def make_accepted(**overrides):
    data = {
        "kind": "accepted",
        "normalized_goal": "测试政策",
        "tags": ["test"],
        "policy_effect": {"people": 0, "treasury": 0, "grain": 0},
        "echo_effects": [],
        "advisor": "臣以为此事可行。",
        "reactions": [
            {"speaker": "tian_bo", "text": "乡野之见,愿闻施行。"},
            {"speaker": "gu_tingzhang", "text": "士绅之议,盼有章法。"},
        ],
        "summary": "本回合无事,天下照旧。",
        "new_echoes": [],
    }
    data.update(overrides)
    return AcceptedCandidate.model_validate(data)


def set_state(db, game_id, **fields):
    row = db.get_game(game_id)
    if row is None:
        raise AssertionError(f"game {game_id} 不存在")
    allowed = {"people", "treasury", "grain", "accepted_turns", "revision", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{k} = ?" for k in updates)
    db._conn.execute(f"UPDATE games SET {assignments} WHERE id = ?", (*updates.values(), game_id))


def insert_echo(db, game_id, echo_id, source_policy_id, created_turn, due_turn, reason="测试回声"):
    with db.transaction() as conn:
        db.insert_echo(
            conn,
            {
                "id": echo_id,
                "game_id": game_id,
                "source_policy_id": source_policy_id,
                "created_turn": created_turn,
                "due_turn": due_turn,
                "reason": reason,
                "status": "pending",
                "resolved_turn": None,
            },
        )


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    yield database
    database.close()


@pytest.fixture()
def service(db):
    return GameService(db, FixtureAdapter())


@pytest.fixture(autouse=True)
def stable_opening(monkeypatch):
    """Existing rule regressions use the legacy baseline, not a random budget.

    Opening-specific tests explicitly inject each of the six real profiles.
    """
    from app.domain.openings import choose_opening
    monkeypatch.setattr("app.services.game_service.choose_opening", lambda: None)
    # Historical schema-1/2/3 regressions remain on their original rule set.
    # Schema-4 tests explicitly use events_enabled=True.
    monkeypatch.setattr("app.services.game_service.EVENTS_DEFAULT", False)
    return choose_opening
