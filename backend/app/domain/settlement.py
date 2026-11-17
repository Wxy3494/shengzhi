from dataclasses import dataclass, field

from .models import (
    EffectDelta,
    GameState,
    INITIAL_GRAIN,
    INITIAL_PEOPLE,
    INITIAL_TREASURY,
    TOTAL_TURNS,
    WIN_THRESHOLD,
)

POLICY_EFFECT_RANGES = {
    "people": (-12, 8),
    "treasury": (-20, 20),
    "grain": (-20, 20),
}
ECHO_EFFECT_RANGES = {
    "people": (-4, 4),
    "treasury": (-10, 10),
    "grain": (-10, 10),
}
TOTAL_BOUNDS = {
    "people": (-12, 8),
    "treasury": (-20, 20),
    "grain": (-20, 20),
}
MAX_NEW_ECHOES = 2
DIMENSIONS = ("people", "treasury", "grain")

REQUIRED_SPEAKER_IDS = ("tian_bo", "song_zhiyuan", "gu_tingzhang")


def initial_state() -> GameState:
    return GameState(
        people=INITIAL_PEOPLE,
        treasury=INITIAL_TREASURY,
        grain=INITIAL_GRAIN,
    )


def in_range(value: int, bounds: tuple[int, int]) -> bool:
    low, high = bounds
    return low <= value <= high


@dataclass
class Settlement:
    before: GameState
    policy_effect: dict
    echo_effects: list[dict]
    bounded_totals: dict
    after: GameState
    applied_effects: EffectDelta
    audit: dict = field(default_factory=dict)


def settle(
    before: GameState,
    policy_effect: dict[str, int],
    echo_effects: list[dict],
) -> Settlement:
    raw_totals = {dim: policy_effect[dim] for dim in DIMENSIONS}
    for echo in echo_effects:
        for dim in DIMENSIONS:
            raw_totals[dim] += echo[dim]

    bounded_totals: dict[str, int] = {}
    for dim in DIMENSIONS:
        low, high = TOTAL_BOUNDS[dim]
        bounded_totals[dim] = max(low, min(high, raw_totals[dim]))

    after_values = {}
    applied_values = {}
    for dim in DIMENSIONS:
        current = getattr(before, dim)
        after = max(0, min(100, current + bounded_totals[dim]))
        after_values[dim] = after
        applied_values[dim] = after - current

    return Settlement(
        before=before,
        policy_effect=dict(policy_effect),
        echo_effects=[dict(e) for e in echo_effects],
        bounded_totals=bounded_totals,
        after=GameState(**after_values),
        applied_effects=EffectDelta(**applied_values),
        audit={
            "raw_totals": raw_totals,
            "bounded_totals": bounded_totals,
            "applied": applied_values,
        },
    )


def apply_execution_constraints(
    before: GameState,
    effect: dict[str, int],
    history: list[dict],
    raw_text: str,
    normalized_goal: str,
    intent: dict | None = None,
) -> tuple[dict[str, int], list[str]]:
    adjusted = dict(effect)
    notes = []
    previous = [
        item
        for item in history
        if (intent is None or intent.get("action") not in ("revoke", "suspend", "resume"))
        and (item["raw_text"].strip() == raw_text.strip()
        or (item["normalized_goal"].strip() == normalized_goal.strip() and (not intent or intent.get("category") == "other"))
        or _same_policy(item, intent))
    ]
    if previous:
        divisor = len(previous) + 1
        for dim in DIMENSIONS:
            if adjusted[dim] > 0:
                adjusted[dim] = int(adjusted[dim] / divisor)
        turns = "、".join(str(item["turn_no"]) for item in previous)
        notes.append(f"与第{turns}回合属于同一政策,新增正向收益折减为原来的 1/{divisor}。")

    resource_ratios = []
    for dim in ("treasury", "grain"):
        cost = -effect[dim]
        if cost > 0:
            available = getattr(before, dim)
            if available < cost:
                resource_ratios.append((dim, available / cost))
    if resource_ratios:
        ratio = min(ratio for _dim, ratio in resource_ratios)
        for dim in DIMENSIONS:
            if adjusted[dim] > 0:
                adjusted[dim] = int(adjusted[dim] * ratio)
        names = "、".join(
            "国库" if dim == "treasury" else "粮储" for dim, _ratio in resource_ratios
        )
        notes.append(f"{names}不足,政策正向收益按可动用资源折减,实际支出不超过现有存量。")

    return adjusted, notes


def _same_policy(item: dict, intent: dict | None) -> bool:
    from .policies import identify, same_scope
    if not intent:
        return False
    old = item.get("policy_intent") or identify(item["raw_text"])
    if old.get("category") == "tax" and old.get("magnitude") != intent.get("magnitude"):
        return False
    # Civil works of the same type in the same region remain the same project;
    # a genuinely different named project can be represented by the model.
    if not same_scope(old, intent):
        return False
    return old.get("project") == intent.get("project")


def attribute_applied(result: Settlement) -> None:
    """Trim capped/clamped components so their displayed sum is the real delta."""
    components = [result.policy_effect, *result.echo_effects]
    for dim in DIMENSIONS:
        difference = sum(c[dim] for c in components) - getattr(result.applied_effects, dim)
        for component in reversed(components):
            if difference > 0 and component[dim] > 0:
                cut = min(difference, component[dim])
                component[dim] -= cut
                difference -= cut
            elif difference < 0 and component[dim] < 0:
                cut = min(-difference, -component[dim])
                component[dim] += cut
                difference += cut


def decide_status(after_people: int, new_turn_count: int) -> str:
    if after_people >= WIN_THRESHOLD:
        return "won"
    if new_turn_count >= TOTAL_TURNS:
        return "lost"
    return "playing"


def validate_candidate_semantics(candidate: dict, due_echoes: list[dict], turn_no: int) -> list[str]:
    """Return a list of error descriptions; empty means valid."""
    errors: list[str] = []

    effect = candidate["policy_effect"]
    for dim in DIMENSIONS:
        if not in_range(effect[dim], POLICY_EFFECT_RANGES[dim]):
            errors.append(f"policy_effect.{dim}={effect[dim]} 超出范围 {POLICY_EFFECT_RANGES[dim]}")

    for idx, echo in enumerate(candidate["echo_effects"]):
        for dim in DIMENSIONS:
            if not in_range(echo[dim], ECHO_EFFECT_RANGES[dim]):
                errors.append(f"echo_effects[{idx}].{dim}={echo[dim]} 超出范围 {ECHO_EFFECT_RANGES[dim]}")
        if not echo.get("explanation", "").strip():
            errors.append(f"echo_effects[{idx}].explanation 为空")

    due_ids = {e["id"] for e in due_echoes}
    submitted_ids = {e["echo_id"] for e in candidate["echo_effects"]}
    if len(submitted_ids) != len(candidate["echo_effects"]):
        errors.append("同一个到期回声不可重复结算")
    if submitted_ids != due_ids:
        missing = sorted(due_ids - submitted_ids)
        extra = sorted(submitted_ids - due_ids)
        if missing:
            errors.append(f"到期回声未覆盖: {missing}")
        if extra:
            errors.append(f"包含非到期或未知回声: {extra}")

    speakers = [r["speaker"] for r in candidate["reactions"]]
    if len(speakers) < 2 or len(speakers) > 3:
        errors.append(f"reactions 数量须为 2 至 3,实际 {len(speakers)}")
    if len(set(speakers)) != len(speakers):
        errors.append("reactions 中存在重复角色")
    for speaker in speakers:
        if speaker not in REQUIRED_SPEAKER_IDS:
            errors.append(f"未知角色 {speaker}")

    new_echoes = candidate["new_echoes"]
    if len(new_echoes) > MAX_NEW_ECHOES:
        errors.append(f"new_echoes 最多 {MAX_NEW_ECHOES} 条,实际 {len(new_echoes)}")
    for idx, echo in enumerate(new_echoes):
        if echo["delay"] not in (1, 2):
            errors.append(f"new_echoes[{idx}].delay={echo['delay']} 只能为 1 或 2")
        if turn_no + echo["delay"] > TOTAL_TURNS:
            errors.append(f"new_echoes[{idx}] 超出第八回合,无法安排")
        if not echo.get("reason", "").strip():
            errors.append(f"new_echoes[{idx}].reason 为空")

    if turn_no >= TOTAL_TURNS and new_echoes:
        errors.append("第八回合不得新建回声")
    if turn_no == TOTAL_TURNS - 1 and any(e["delay"] != 1 for e in new_echoes):
        errors.append("第七回合回声只能安排在第八回合(delay=1)")

    return errors
