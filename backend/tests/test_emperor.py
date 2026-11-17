"""Post-game portraits: real trace evidence, caching and isolated failure."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.games import router
from app.domain.emperors import EMPERORS
from app.llm.base import ModelOutputInvalid, ModelTimeout
from app.llm.emperor_review import EmperorReview, generate_emperor_review, validate_review
from app.services.game_service import GameService, ServiceError
from app.storage.sqlite import Database
from conftest import ScriptedAdapter, make_accepted, set_state


def valid_review():
    return {"emperor_id": "han_wendi", "biography": '汉文帝是西汉皇帝，在位于公元前180至前157年。他的重农诏令关注农业生产、歉收与粮食不足，反省政务是否失当，以及宫廷开支是否过多，并要求官员提出改善办法。这些记载反映了他对农事与国家开支的关注，也为理解西汉时期的休养生息提供了材料。'}


class Historian(ScriptedAdapter):
    def __init__(self):
        super().__init__(default=make_accepted())
        self.reviews = 0
        self.failure = None

    def assess_emperor(self, detail):
        self.reviews += 1
        if self.failure:
            raise self.failure
        return valid_review()


def ended(db, status="won"):
    adapter = Historian()
    service = GameService(db, adapter)
    game = service.create_game()["game"]
    for index, text in enumerate(["修渠灌田", "节省宫廷用度"]):
        service.submit_turn(game["id"], str(index), index, text)
    set_state(db, game["id"], status=status)
    return service, adapter, game["id"]


def test_only_finished_games_and_real_model(service):
    game_id = service.create_game()["game"]["id"]
    for identifier, code in [(game_id, "GAME_NOT_FINISHED"), ("missing", "GAME_NOT_FOUND")]:
        for call in [service.get_emperor_review, service.generate_emperor_review]:
            with pytest.raises(ServiceError) as error:
                call(identifier)
            assert error.value.code == code
    set_state(service.db, game_id, status="lost")
    with pytest.raises(ServiceError, match="真实模型") as error:
        service.generate_emperor_review(game_id)
    assert error.value.status_code == 503


@pytest.mark.parametrize("status", ["won", "lost"])
def test_cached_portrait_preserves_every_gameplay_record(db, status):
    service, adapter, game_id = ended(db, status)
    before = service.get_game_detail(game_id)
    assert service.get_emperor_review(game_id)["state"] == "not_generated"
    result = service.generate_emperor_review(game_id)
    assert service.generate_emperor_review(game_id) == result
    assert adapter.reviews == 1
    assert service.get_game_detail(game_id) == before
    assert set(result["review"]) == {"emperor_id", "biography"}
    assert result["review"]["biography"] == valid_review()["biography"]
    path = db._conn.execute("PRAGMA database_list").fetchone()[2]
    other = Database(path)
    try:
        # Reopening with a fixture adapter must still return the saved real assessment.
        assert GameService(other, ScriptedAdapter()).generate_emperor_review(game_id) == result
    finally:
        other.close()


@pytest.mark.parametrize("failure,code", [(ModelTimeout("slow"), "MODEL_TIMEOUT"), (ModelOutputInvalid("bad"), "MODEL_OUTPUT_INVALID")])
def test_failed_review_is_retryable_without_changing_ending(db, failure, code):
    service, adapter, game_id = ended(db)
    before = service.get_game_detail(game_id)
    adapter.failure = failure
    with pytest.raises(ServiceError) as error:
        service.generate_emperor_review(game_id)
    assert error.value.code == code and error.value.retryable
    assert service.get_emperor_review(game_id)["state"] == "not_generated"
    assert service.get_game_detail(game_id) == before
    adapter.failure = None
    assert service.generate_emperor_review(game_id)["state"] == "ready"
    assert adapter.reviews == 2


def test_concurrent_requests_generate_once(db):
    service, adapter, game_id = ended(db)
    started, release = threading.Event(), threading.Event()
    def assess(detail):
        adapter.reviews += 1
        started.set()
        assert release.wait(3)
        return valid_review()
    adapter.assess_emperor = assess
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.generate_emperor_review, game_id)
        assert started.wait(3)
        second = executor.submit(service.generate_emperor_review, game_id)
        release.set()
        assert first.result() == second.result()
    assert adapter.reviews == 1


def test_storage_failure_preserves_ending_and_allows_retry(db, monkeypatch):
    service, _, game_id = ended(db)
    before = service.get_game_detail(game_id)
    original_save = db.save_emperor_review
    def fail(*args):
        raise sqlite3.OperationalError("test disk failure")
    monkeypatch.setattr(db, "save_emperor_review", fail)
    with pytest.raises(ServiceError) as error:
        service.generate_emperor_review(game_id)
    assert error.value.code == "SAVE_FAILED" and error.value.retryable
    assert service.get_game_detail(game_id) == before
    assert service.get_emperor_review(game_id)["state"] == "not_generated"
    monkeypatch.setattr(db, "save_emperor_review", original_save)
    assert service.generate_emperor_review(game_id)["state"] == "ready"


@pytest.mark.parametrize("change", [
    {"emperor_id": "invented_emperor"},
    {"biography": valid_review()["biography"] + "treasury下降，confidence为medium。"},
    {"biography": valid_review()["biography"] + "本局玩家的行为因此很像汉文帝。"},
    {"biography": valid_review()["biography"] + "他于2026年巡游。"},
])

def test_model_cannot_invent_emperor_turn_or_year(db, change):
    service, _, game_id = ended(db)
    review = EmperorReview.model_validate({**valid_review(), **change})
    with pytest.raises(ValueError):
        validate_review(review, service.get_game_detail(game_id))


def test_schema_repair_uses_full_history_and_shared_budget(db):
    service, _, game_id = ended(db)
    detail = service.get_game_detail(game_id)
    class Provider:
        timeout = 10
        calls = []
        def _call(self, messages, temperature, budget):
            self.calls.append((json.loads(messages[1]["content"]), budget))
            return "{}" if len(self.calls) == 1 else json.dumps(valid_review(), ensure_ascii=False)
    provider = Provider()
    assert generate_emperor_review(provider, detail).emperor_id == "han_wendi"
    assert [item["raw_text"] for item in provider.calls[0][0]["settled_history"]] == [item["raw_text"] for item in detail["history"]]
    assert 0 < provider.calls[1][1] <= provider.calls[0][1] <= 10
    assert len(provider.calls[0][0]["emperor_library"]) == len(EMPERORS)


def test_api_read_generate_and_cache(db):
    service, adapter, game_id = ended(db)
    app = FastAPI()
    app.include_router(router)
    app.state.game_service = service
    with TestClient(app) as client:
        path = f"/api/games/{game_id}/emperor"
        assert client.get(path).json()["state"] == "not_generated"
        generated = client.post(path)
        assert generated.status_code == 200
        assert client.get(path).json() == generated.json() == client.post(path).json()
        assert client.post("/api/games/missing/emperor").status_code == 404
    assert adapter.reviews == 1


def test_old_assessment_cache_projects_to_biography_without_rewriting(db):
    service, adapter, game_id = ended(db)
    original = service.generate_emperor_review(game_id)
    legacy = {**original, "review": {**original["review"], "overview": "旧版匹配理由", "evidence": [{"turn_no": 1}]}}
    db._conn.execute("UPDATE emperor_reviews SET response_json=? WHERE game_id=?", (json.dumps(legacy, ensure_ascii=False), game_id))
    assert service.generate_emperor_review(game_id) == original
    assert adapter.reviews == 1
    assert db.get_emperor_review(game_id, original["game_revision"]) == legacy


def test_new_model_contract_does_not_accept_reason_fields():
    with pytest.raises(ValueError):
        EmperorReview.model_validate({**valid_review(), "overview": "不再生成理由"})
