"""M2 存档与故障恢复测试:S01-S11。"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.llm.base import ModelOutputInvalid, ModelTimeout
from app.services.game_service import GameService, ServiceError
from app.storage.sqlite import Database

from conftest import ScriptedAdapter, make_accepted, set_state

RELIEF_TEXT = "今夏旱情频仍,着户部拨银赈济灾民,开仓放粮。"
WATER_TEXT = "着工部征调民夫,兴修水利,加固河堤。"


def _submit(service, game_id, revision, request_id, text=RELIEF_TEXT):
    return service.submit_turn(game_id, request_id, revision, text)


# ---------- S01 两回合后刷新:从服务端恢复相同状态与历史 ----------


def test_s01_refresh_restores_state(service, db, tmp_path):
    game = service.create_game()["game"]
    first = _submit(service, game["id"], 0, "s01-1")
    second = _submit(service, game["id"], 1, "s01-2", WATER_TEXT)
    assert second["game"]["accepted_turns"] == 2

    # 模拟刷新:重新连接同一数据库文件读取
    path = str(tmp_path / "test.db")
    fresh_db = Database(path)
    try:
        fresh_service = GameService(fresh_db, service.adapter)
        detail = fresh_service.get_game_detail(game["id"])
    finally:
        fresh_db.close()

    assert detail["game"]["people"] == second["game"]["people"]
    assert detail["game"]["treasury"] == second["game"]["treasury"]
    assert detail["game"]["grain"] == second["game"]["grain"]
    assert detail["game"]["revision"] == 2
    assert detail["game"]["accepted_turns"] == 2
    assert len(detail["history"]) == 2
    assert detail["history"][0]["raw_text"] == RELIEF_TEXT
    assert detail["history"][1]["raw_text"] == WATER_TEXT
    assert detail["game"]["status"] == "playing"


# ---------- S02 同 request_id 同内容两次 → 结果相同,只生成一条政策 ----------


def test_s02_idempotent_replay(service, db):
    game = service.create_game()["game"]
    first = _submit(service, game["id"], 0, "s02-1")
    second = _submit(service, game["id"], 0, "s02-1")
    assert second == first
    detail = service.get_game_detail(game["id"])
    assert len(detail["history"]) == 1
    assert detail["game"]["revision"] == 1


# ---------- S03 同 request_id 改 policy_text → 409 ----------


def test_s03_reused_key_different_text(service, db):
    game = service.create_game()["game"]
    _submit(service, game["id"], 0, "s03-1")
    with pytest.raises(ServiceError) as exc:
        _submit(service, game["id"], 0, "s03-1", WATER_TEXT)
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert exc.value.status_code == 409
    assert db.get_game(game["id"])["revision"] == 1


# ---------- S04 并发同 revision → 仅一个提交,另一个 409 STALE_REVISION ----------


def test_s04_concurrent_same_revision(service, db):
    game = service.create_game()["game"]
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker(request_id):
        barrier.wait()
        try:
            results.append(_submit(service, game["id"], 0, request_id))
        except ServiceError as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, f"s04-{i}") for i in range(2)]
        for future in futures:
            future.result()

    assert len(results) == 1
    assert len(errors) == 1
    assert errors[0].code == "STALE_REVISION"
    assert errors[0].status_code == 409
    assert db.get_game(game["id"])["revision"] == 1
    assert len(service.get_game_detail(game["id"])["history"]) == 1


# ---------- S05 模型超时/输出不合法 → 状态不变,可重试 ----------


def test_s05_model_timeout_keeps_state(service, db):
    game = service.create_game()["game"]
    svc = GameService(db, ScriptedAdapter(default=ModelTimeout("慢")))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "s05-1", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_TIMEOUT"
    assert exc.value.status_code == 504
    assert exc.value.retryable is True
    after = db.get_game(game["id"])
    assert after["revision"] == 0
    assert after["accepted_turns"] == 0
    assert db.find_request_record(game["id"], "s05-1") is None


def test_s05_model_invalid_output_keeps_state(service, db):
    game = service.create_game()["game"]
    svc = GameService(db, ScriptedAdapter(default=ModelOutputInvalid("坏")))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "s05-2", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    assert exc.value.retryable is True
    assert db.get_game(game["id"])["revision"] == 0


def test_s05_semantic_violation_keeps_state(service, db):
    game = service.create_game()["game"]
    bad = make_accepted(policy_effect={"people": 99, "treasury": 0, "grain": 0})
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "s05-3", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    assert db.get_game(game["id"])["revision"] == 0
    assert db.find_request_record(game["id"], "s05-3") is None


# ---------- S06 写入后提交前注入存储异常 → 整体回滚,回声未被消费 ----------


def test_s06_transaction_rollback(service, db, monkeypatch):
    game = service.create_game()["game"]
    first_candidate = make_accepted(
        policy_effect={"people": 5, "treasury": 0, "grain": 0},
        new_echoes=[{"delay": 1, "reason": "核验后续影响"}],
    )
    svc = GameService(db, ScriptedAdapter(default=first_candidate))
    first = svc.submit_turn(game["id"], "s06-1", 0, RELIEF_TEXT)
    assert first["game"]["revision"] == 1
    due = db.get_due_echoes(game["id"], 2)
    assert len(due) == 1
    due_id = due[0]["id"]

    def boom(conn, record):
        raise RuntimeError("注入存储故障")

    monkeypatch.setattr(db, "insert_request_record", boom)
    second_candidate = make_accepted(
        policy_effect={"people": 0, "treasury": 0, "grain": 0},
        echo_effects=[{"echo_id": due_id, "people": 1, "treasury": 0, "grain": 0, "explanation": "到期回声"}],
    )
    svc2 = GameService(db, ScriptedAdapter(default=second_candidate))
    with pytest.raises(ServiceError) as exc:
        svc2.submit_turn(game["id"], "s06-2", 1, WATER_TEXT)
    assert exc.value.code == "SAVE_FAILED"
    assert exc.value.status_code == 500
    assert exc.value.retryable is True

    after = db.get_game(game["id"])
    assert after["revision"] == 1
    assert after["accepted_turns"] == 1
    assert len(service.get_game_detail(game["id"])["history"]) == 1
    remaining = db.get_pending_echoes(game["id"])
    assert [e["id"] for e in remaining] == [due_id]


# ---------- S07 提交成功但客户端丢失响应 → GET 确认后同 request_id 重放 ----------


def test_s07_replay_after_lost_response(service, db):
    game = service.create_game()["game"]
    first = _submit(service, game["id"], 0, "s07-1")
    detail = service.get_game_detail(game["id"])
    assert detail["game"]["revision"] == 1
    assert len(detail["history"]) == 1
    replay = _submit(service, game["id"], 0, "s07-1")
    assert replay == first
    assert len(service.get_game_detail(game["id"])["history"]) == 1


# ---------- S08 最后一回合成功后重试同 request_id → 重放终局结果 ----------


def test_s08_replay_terminal_result(service, db):
    game = service.create_game()["game"]
    set_state(db, game["id"], people=79, accepted_turns=7, revision=7)
    svc = GameService(db, ScriptedAdapter(default=make_accepted(policy_effect={"people": 0, "treasury": 0, "grain": 0})))
    first = svc.submit_turn(game["id"], "s08-1", 7, RELIEF_TEXT)
    assert first["game"]["status"] == "lost"
    replay = svc.submit_turn(game["id"], "s08-1", 7, RELIEF_TEXT)
    assert replay == first
    assert replay["game"]["status"] == "lost"


# ---------- S09 同 request_id 改 expected_revision → 409 ----------


def test_s09_reused_key_different_revision(service, db):
    game = service.create_game()["game"]
    _submit(service, game["id"], 0, "s09-1")
    with pytest.raises(ServiceError) as exc:
        _submit(service, game["id"], 1, "s09-1")
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert exc.value.status_code == 409
    assert db.get_game(game["id"])["revision"] == 1


# ---------- S10 重开游戏:新局初值正确,旧局可读 ----------


def test_s10_new_game_keeps_old_readable(service, db):
    game_a = service.create_game()["game"]
    _submit(service, game_a["id"], 0, "s10-a")
    game_b = service.create_game()["game"]
    assert game_b["id"] != game_a["id"]
    assert game_b["people"] == 50
    assert game_b["treasury"] == 60
    assert game_b["grain"] == 60
    assert game_b["accepted_turns"] == 0
    assert game_b["status"] == "playing"
    detail_a = service.get_game_detail(game_a["id"])
    assert len(detail_a["history"]) == 1
    assert detail_a["game"]["accepted_turns"] == 1


# ---------- S11 读取未知 game_id → 404,可新建,不覆盖 ----------


def test_s11_unknown_game(service):
    assert service.get_game_detail("no-such-id") is None
    with pytest.raises(ServiceError) as exc:
        _submit(service, "no-such-id", 0, "s11-1")
    assert exc.value.code == "GAME_NOT_FOUND"
    assert exc.value.status_code == 404
    game = service.create_game()["game"]
    assert game["people"] == 50
