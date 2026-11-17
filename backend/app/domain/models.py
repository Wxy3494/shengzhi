from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

YEAR_NAMES = [
    "元", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "二十一", "二十二", "二十三", "二十四",
]

INITIAL_PEOPLE = 50
INITIAL_TREASURY = 60
INITIAL_GRAIN = 60
TOTAL_TURNS = 8
YEARS_PER_TURN = 3
TOTAL_YEARS = TOTAL_TURNS * YEARS_PER_TURN
WIN_THRESHOLD = 80
ENGINE_VERSION = "2026.11.08-codex8"

GameStatus = Literal["playing", "won", "lost"]
SpeakerId = Literal["tian_bo", "song_zhiyuan", "gu_tingzhang"]

SPEAKER_LABELS = {
    "tian_bo": "田伯 · 乡老",
    "song_zhiyuan": "宋知远 · 商帮会首",
    "gu_tingzhang": "顾廷章 · 士绅代表",
}
SPEAKER_CHANNELS = {
    "tian_bo": "民间陈情",
    "song_zhiyuan": "商路来报",
    "gu_tingzhang": "地方呈报",
}


def period_name(turn_no: int) -> str:
    start_year = (turn_no - 1) * YEARS_PER_TURN + 1
    end_year = start_year + YEARS_PER_TURN - 1
    return f"承和{YEAR_NAMES[start_year - 1]}年至{YEAR_NAMES[end_year - 1]}年"


class GameState(BaseModel):
    people: int = Field(ge=0, le=100)
    treasury: int = Field(ge=0, le=100)
    grain: int = Field(ge=0, le=100)


class EffectDelta(BaseModel):
    people: int = Field(ge=-100, le=100)
    treasury: int = Field(ge=-100, le=100)
    grain: int = Field(ge=-100, le=100)


class GameView(BaseModel):
    id: str
    schema_version: int
    revision: int
    accepted_turns: int
    status: GameStatus
    people: int
    treasury: int
    grain: int
    created_at: str
    updated_at: str
    realm: dict | None = None
    ending: dict | None = None
    opening: dict | None = None
    conditions: dict | None = None
    events: dict | None = None
    diplomacy: dict | None = None


class Reaction(BaseModel):
    speaker: SpeakerId
    text: str


class EchoEffect(BaseModel):
    echo_id: str
    people: int
    treasury: int
    grain: int
    explanation: str


class TurnResultView(BaseModel):
    id: str
    policy_id: str
    turn_no: int
    raw_text: str
    normalized_goal: str
    before: GameState
    applied_effects: EffectDelta
    after: GameState
    advisor: str
    reactions: list[Reaction]
    summary: str
    constraint_notes: list[str] = Field(default_factory=list)
    policy_analysis: dict = Field(default_factory=dict)
    narration_source: Literal["model", "fixture", "legacy"] = "legacy"
    policy_intent: dict = Field(default_factory=dict)
    policy_status: Literal["active", "suspended", "revoked", "completed"] = "active"
    execution: dict = Field(default_factory=dict)
    events: dict | None = None
    realm: dict | None = None
    echo_effects: list[EchoEffect]
    new_echoes: list["NewEchoView"]


class NewEchoView(BaseModel):
    id: str
    source_policy_id: str
    delay: int
    due_turn: int
    created_turn: int
    reason: str
    effect_kind: Literal["consequence", "execution"] = "consequence"


class EchoView(BaseModel):
    id: str
    source_policy_id: str
    due_turn: int
    reason: str
    effect_kind: Literal["consequence", "execution"] = "consequence"
    status: Literal["pending", "resolved"]
    created_turn: int
    resolved_turn: int | None = None


class GameDetail(BaseModel):
    game: GameView
    history: list[TurnResultView]
    echoes: list[EchoView]


class TurnRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=64, validation_alias=AliasChoices('request_id', 'idempotencyKey'))
    expected_revision: int = Field(ge=0)
    expected_turn: int | None = Field(default=None, ge=1, le=8, validation_alias=AliasChoices('expected_turn', 'expectedTurn'))
    policy_text: str = Field(min_length=1, max_length=600)

class PolicyPreviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    policy_text: str = Field(min_length=1,max_length=500)

class DiplomacyRequest(BaseModel):
    request_id: str=Field(min_length=1,max_length=64,validation_alias=AliasChoices('request_id','idempotencyKey'))
    expected_revision: int=Field(ge=0)
    action: Literal['accept','reject','counter']
    text: str=Field(default='',max_length=500)
    proposal_id: str | None=Field(default=None,max_length=80)

class PolicyPreviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    policy_text: str = Field(min_length=1,max_length=500)


class AcceptedResponse(BaseModel):
    kind: Literal["accepted"] = "accepted"
    game: GameView
    result: TurnResultView
    policy_statuses: dict[str, str] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool = False
