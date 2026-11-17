"""M2 API 层测试:HTTP 状态码与错误结构。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.games import router as games_router
from app.api.health import router as health_router
from app.services.game_service import GameService

RELIEF_TEXT = "今夏旱情频仍,着户部拨银赈济灾民,开仓放粮。"


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.state.game_service = GameService(db, __import__("app.llm.fixture", fromlist=["FixtureAdapter"]).FixtureAdapter())
    app.include_router(games_router)
    app.include_router(health_router)
    with TestClient(app) as c:
        yield c


def test_api_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["period"] == "承和元年至三年"
    assert body["years_per_turn"] == 3
    assert body["total_years"] == 24
    assert body["llm_mode"] in ("fixture", "live")


def test_api_create_game(client):
    resp = client.post("/api/games")
    assert resp.status_code == 201
    game = resp.json()["game"]
    assert game["people"] == 50
    assert game["treasury"] == 60
    assert game["grain"] == 60
    assert game["accepted_turns"] == 0


def test_api_turn_accepted(client):
    game_id = client.post("/api/games").json()["game"]["id"]
    resp = client.post(
        f"/api/games/{game_id}/turns",
        json={"request_id": "api-1", "expected_revision": 0, "policy_text": RELIEF_TEXT},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "accepted"
    assert body["game"]["people"] == 55
    assert body["game"]["revision"] == 1


def test_api_whitespace_422(client):
    game_id = client.post("/api/games").json()["game"]["id"]
    resp = client.post(
        f"/api/games/{game_id}/turns",
        json={"request_id": "api-2", "expected_revision": 0, "policy_text": "   "},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INVALID_POLICY_TEXT"


def test_api_501_chars_422(client):
    game_id = client.post("/api/games").json()["game"]["id"]
    resp = client.post(
        f"/api/games/{game_id}/turns",
        json={"request_id": "api-3", "expected_revision": 0, "policy_text": "赈" * 501},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INVALID_POLICY_TEXT"


def test_api_unknown_game_404(client):
    resp = client.get("/api/games/no-such-id")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "GAME_NOT_FOUND"
    resp = client.post(
        "/api/games/no-such-id/turns",
        json={"request_id": "api-4", "expected_revision": 0, "policy_text": RELIEF_TEXT},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "GAME_NOT_FOUND"


def test_api_stale_revision_409(client):
    game_id = client.post("/api/games").json()["game"]["id"]
    ok = client.post(
        f"/api/games/{game_id}/turns",
        json={"request_id": "api-5a", "expected_revision": 0, "policy_text": RELIEF_TEXT},
    )
    assert ok.status_code == 200
    stale = client.post(
        f"/api/games/{game_id}/turns",
        json={"request_id": "api-5b", "expected_revision": 0, "policy_text": RELIEF_TEXT},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "STALE_REVISION"
