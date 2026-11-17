import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    accepted_turns INTEGER NOT NULL,
    status TEXT NOT NULL,
    people INTEGER NOT NULL,
    treasury INTEGER NOT NULL,
    grain INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    turn_no INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_goal TEXT NOT NULL,
    tags TEXT NOT NULL,
    UNIQUE(game_id, turn_no)
);
CREATE TABLE IF NOT EXISTS turn_results (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    turn_no INTEGER NOT NULL,
    before_people INTEGER NOT NULL,
    before_treasury INTEGER NOT NULL,
    before_grain INTEGER NOT NULL,
    after_people INTEGER NOT NULL,
    after_treasury INTEGER NOT NULL,
    after_grain INTEGER NOT NULL,
    applied_people INTEGER NOT NULL,
    applied_treasury INTEGER NOT NULL,
    applied_grain INTEGER NOT NULL,
    advisor TEXT NOT NULL,
    reactions TEXT NOT NULL,
    summary TEXT NOT NULL,
    echo_effects TEXT NOT NULL,
    new_echoes TEXT NOT NULL,
    audit TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS echoes (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    source_policy_id TEXT NOT NULL,
    created_turn INTEGER NOT NULL,
    due_turn INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    resolved_turn INTEGER
);
CREATE TABLE IF NOT EXISTS request_records (
    game_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (game_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_echoes_game_due ON echoes(game_id, due_turn, status);
CREATE TABLE IF NOT EXISTS emperor_reviews (
    game_id TEXT PRIMARY KEY,
    game_revision INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        # Additive migration: existing saves keep their IDs and all past results.
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(policies)")}
        if "metadata" not in columns:
            self._conn.execute("ALTER TABLE policies ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        if "status" not in columns:
            self._conn.execute("ALTER TABLE policies ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        game_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(games)")}
        if "realm_json" not in game_columns:
            self._conn.execute("ALTER TABLE games ADD COLUMN realm_json TEXT NOT NULL DEFAULT '{}'")
        for column in ("opening_json", "conditions_json", "briefing_json", "events_json", "diplomacy_json"):
            if column not in game_columns:
                self._conn.execute(f"ALTER TABLE games ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'")
        echo_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(echoes)")}
        if "effect_kind" not in echo_columns:
            self._conn.execute("ALTER TABLE echoes ADD COLUMN effect_kind TEXT NOT NULL DEFAULT 'consequence'")
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # ---- reads ----

    def get_game(self, game_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM games WHERE id = ?", (game_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_emperor_review(self, game_id: str, revision: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT response_json FROM emperor_reviews WHERE game_id=? AND game_revision=?", (game_id, revision)).fetchone()
            return json.loads(row["response_json"]) if row else None

    def save_emperor_review(self, conn, game_id: str, revision: int, response: dict) -> None:
        conn.execute("""INSERT INTO emperor_reviews(game_id,game_revision,response_json,created_at)
            VALUES(?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET game_revision=excluded.game_revision,
            response_json=excluded.response_json,created_at=excluded.created_at
            WHERE emperor_reviews.game_revision<>excluded.game_revision""",
            (game_id, revision, json.dumps(response, ensure_ascii=False), response["generated_at"]))



    def get_history(self, game_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT r.*, p.raw_text, p.normalized_goal, p.metadata, p.status AS policy_status
                FROM turn_results r
                JOIN policies p ON p.id = r.policy_id
                WHERE r.game_id = ?
                ORDER BY r.turn_no ASC
                """,
                (game_id,),
            ).fetchall()
            history = []
            for row in rows:
                item = dict(row)
                history.append(self._decode_result_row(item))
            return history

    def get_echoes(self, game_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM echoes WHERE game_id = ? ORDER BY due_turn ASC",
                (game_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_due_echoes(self, game_id: str, turn_no: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM echoes WHERE game_id = ? AND due_turn = ? AND status = 'pending'",
                (game_id, turn_no),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_pending_echoes(self, game_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM echoes WHERE game_id = ? AND status = 'pending' ORDER BY due_turn ASC",
                (game_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def find_request_record(self, game_id: str, request_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM request_records WHERE game_id = ? AND request_id = ?",
                (game_id, request_id),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["response"] = json.loads(item["response_json"])
            return item

    # ---- writes (call inside transaction) ----

    def insert_game(self, conn: sqlite3.Connection, game: dict) -> None:
        conn.execute(
            """
            INSERT INTO games (id, schema_version, revision, accepted_turns, status,
                               people, treasury, grain, created_at, updated_at)
            VALUES (:id, :schema_version, :revision, :accepted_turns, :status,
                    :people, :treasury, :grain, :created_at, :updated_at)
            """,
            game,
        )

    def insert_policy(self, conn: sqlite3.Connection, policy: dict) -> None:
        conn.execute(
            """
            INSERT INTO policies (id, game_id, turn_no, raw_text, normalized_goal, tags)
            VALUES (:id, :game_id, :turn_no, :raw_text, :normalized_goal, :tags)
            """,
            policy,
        )
        conn.execute("UPDATE policies SET metadata = ?, status = ? WHERE id = ?", (
            policy.get("metadata", "{}"), policy.get("status", "active"), policy["id"]))

    def update_policy_status(self, conn: sqlite3.Connection, policy_id: str, status: str) -> None:
        conn.execute("UPDATE policies SET status = ? WHERE id = ?", (status, policy_id))

    def insert_turn_result(self, conn: sqlite3.Connection, result: dict) -> None:
        conn.execute(
            """
            INSERT INTO turn_results (
                id, game_id, policy_id, turn_no,
                before_people, before_treasury, before_grain,
                after_people, after_treasury, after_grain,
                applied_people, applied_treasury, applied_grain,
                advisor, reactions, summary, echo_effects, new_echoes, audit)
            VALUES (
                :id, :game_id, :policy_id, :turn_no,
                :before_people, :before_treasury, :before_grain,
                :after_people, :after_treasury, :after_grain,
                :applied_people, :applied_treasury, :applied_grain,
                :advisor, :reactions, :summary, :echo_effects, :new_echoes, :audit)
            """,
            result,
        )

    def insert_echo(self, conn: sqlite3.Connection, echo: dict) -> None:
        conn.execute(
            """
            INSERT INTO echoes (id, game_id, source_policy_id, created_turn, due_turn,
                                reason, status, resolved_turn)
            VALUES (:id, :game_id, :source_policy_id, :created_turn, :due_turn,
                    :reason, :status, :resolved_turn)
            """,
            echo,
        )
        conn.execute("UPDATE echoes SET effect_kind = ? WHERE id = ?", (echo.get("effect_kind", "consequence"), echo["id"]))

    def resolve_echo(self, conn: sqlite3.Connection, echo_id: str, turn_no: int) -> None:
        conn.execute(
            "UPDATE echoes SET status = 'resolved', resolved_turn = ? WHERE id = ?",
            (turn_no, echo_id),
        )

    def update_game_after_turn(self, conn: sqlite3.Connection, game: dict) -> None:
        conn.execute(
            """
            UPDATE games
            SET revision = :revision, accepted_turns = :accepted_turns, status = :status,
                people = :people, treasury = :treasury, grain = :grain, updated_at = :updated_at
            WHERE id = :id
            """,
            game,
        )

    def save_realm(self, conn, game_id: str, realm: dict) -> None:
        conn.execute("UPDATE games SET realm_json=? WHERE id=?", (json.dumps(realm, ensure_ascii=False), game_id))

    def save_events(self, conn, game_id, events):
        conn.execute("UPDATE games SET events_json=? WHERE id=?", (json.dumps(events, ensure_ascii=False), game_id))

    def save_opening(self, conn, game_id, opening, conditions):
        conn.execute("UPDATE games SET opening_json=?,conditions_json=? WHERE id=?",
                     (json.dumps(opening, ensure_ascii=False), json.dumps(conditions, ensure_ascii=False), game_id))

    def save_conditions(self, conn, game_id, conditions):
        conn.execute("UPDATE games SET conditions_json=? WHERE id=?", (json.dumps(conditions, ensure_ascii=False), game_id))

    def save_briefing(self, conn, game_id, briefing):
        conn.execute("UPDATE games SET briefing_json=? WHERE id=?", (json.dumps(briefing, ensure_ascii=False), game_id))

    def insert_request_record(self, conn: sqlite3.Connection, record: dict) -> None:
        conn.execute(
            """
            INSERT INTO request_records (game_id, request_id, request_hash,
                                         expected_revision, response_json, created_at)
            VALUES (:game_id, :request_id, :request_hash,
                    :expected_revision, :response_json, :created_at)
            """,
            record,
        )

    @staticmethod
    def _decode_result_row(item: dict) -> dict:
        audit = json.loads(item["audit"])
        result = {
            "id": item["id"],
            "policy_id": item["policy_id"],
            "turn_no": item["turn_no"],
            "raw_text": item["raw_text"],
            "normalized_goal": item["normalized_goal"],
            "before": {
                "people": item["before_people"],
                "treasury": item["before_treasury"],
                "grain": item["before_grain"],
            },
            "after": {
                "people": item["after_people"],
                "treasury": item["after_treasury"],
                "grain": item["after_grain"],
            },
            "applied_effects": {
                "people": item["applied_people"],
                "treasury": item["applied_treasury"],
                "grain": item["applied_grain"],
            },
            "advisor": item["advisor"],
            "reactions": json.loads(item["reactions"]),
            "summary": item["summary"],
            "constraint_notes": audit.get("constraint_notes", []),
            "policy_analysis": audit.get("policy_analysis", {}),
            "narration_source": audit.get("narration_source", "legacy"),
            "policy_intent": json.loads(item.get("metadata", "{}")),
            "policy_status": item.get("policy_status", "active"),
            "execution": audit.get("execution", {}),
            "realm": audit.get("execution", {}).get("realm"),
            "events": audit.get("events"),
            "echo_effects": json.loads(item["echo_effects"]),
            "new_echoes": json.loads(item["new_echoes"]),
        }
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
