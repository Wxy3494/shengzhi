import json
from typing import Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, field_validator


class PolicyEffectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    people: StrictInt
    treasury: StrictInt
    grain: StrictInt


class EchoEffectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    echo_id: str = Field(min_length=1, max_length=64)
    people: StrictInt
    treasury: StrictInt
    grain: StrictInt
    explanation: str = Field(min_length=1, max_length=300)


class ReactionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker: Literal["tian_bo", "song_zhiyuan", "gu_tingzhang"]
    text: str = Field(min_length=1, max_length=300)

    @field_validator('speaker', mode='before')
    @classmethod
    def canonical_speaker(cls, value):
        # Exact known identities only; never invent or silently drop a role.
        return {'田伯':'tian_bo','宋知远':'song_zhiyuan','顾廷章':'gu_tingzhang'}.get(value,value) if isinstance(value,str) else value


class NewEchoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delay: StrictInt
    reason: str = Field(min_length=1, max_length=300)
    effect_kind: Literal["consequence", "execution"] = "consequence"


class PolicyIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(default="other", max_length=40)
    region: str = Field(default="全境", max_length=80)
    project: str = Field(default="", max_length=80)
    action: Literal["enact", "maintain", "revoke", "suspend", "resume"] = "enact"
    magnitude: Literal["unspecified", "moderate", "half", "full", "unchanged", "restore"] = "unspecified"
    duration_years: int | None = Field(default=None, ge=1, le=24)
    prohibitions: list[str] = Field(default_factory=list, max_length=12)


class PolicyRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: str = Field(min_length=1, max_length=160)
    consequence: str = Field(min_length=1, max_length=160)
    likelihood: Literal["low", "medium", "high"]
    horizon: Literal["current", "delayed"]

    @field_validator('likelihood', 'horizon', mode='before')
    @classmethod
    def translate_enum(cls, value):
        # Known language aliases only; these describe prose, never state effects.
        return {'低':'low','中':'medium','中等':'medium','高':'high','当前':'current','当下':'current','后续':'delayed','延后':'delayed','延迟':'delayed'}.get(value,value) if isinstance(value,str) else value


class PolicyAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benefits: list[str] = Field(default_factory=list, max_length=3)
    costs: list[str] = Field(default_factory=list, max_length=3)
    risks: list[PolicyRisk] = Field(default_factory=list, max_length=3)
    effect_basis: str = Field(default="", max_length=250)


class NarrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    advisor: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=150)
    policy_analysis: PolicyAnalysis
    reactions: list[ReactionModel] = Field(min_length=3, max_length=3)
    echo_explanations: dict[str, str] = Field(validation_alias=AliasChoices('echo_explanations','echo_explainations'))
    new_echo_reasons: list[str] = Field(max_length=2)


class EventNarrationModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    advisor: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=150)
    tian_bo: str = Field(min_length=1,max_length=300)
    song_zhiyuan: str = Field(min_length=1,max_length=300)
    gu_tingzhang: str = Field(min_length=1,max_length=300)
    tradeoff: str = Field(min_length=1,max_length=250)
    policy_analysis: PolicyAnalysis | None = None


class AcceptedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["accepted"]
    normalized_goal: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=8)
    policy_intent: PolicyIntent = Field(default_factory=PolicyIntent)
    policy_analysis: PolicyAnalysis = Field(default_factory=PolicyAnalysis)
    policy_effect: PolicyEffectModel
    echo_effects: list[EchoEffectModel] = Field(default_factory=list, max_length=8)
    advisor: str = Field(min_length=1, max_length=300)
    reactions: list[ReactionModel] = Field(min_length=2, max_length=3)
    new_echoes: list[NewEchoModel] = Field(default_factory=list, max_length=2, validation_alias=AliasChoices('new_echoes','new_echoffects'))
    summary: str = Field(min_length=1, max_length=150)


class ClarificationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["clarification"]
    warning_type: Literal["anachronism", "multiple_goals", "not_policy", "unclear"]
    message: str = Field(min_length=1, max_length=300)

    @field_validator('warning_type',mode='before')
    @classmethod
    def translate_warning(cls,value):
        return {'时代错位':'anachronism','多个目标':'multiple_goals','非政令':'not_policy','语义不明':'unclear'}.get(value,value) if isinstance(value,str) else value


Candidate = Union[AcceptedCandidate, ClarificationCandidate]

_candidate_adapter = TypeAdapter(Candidate)

OUTPUT_SCHEMA_TEXT = """
输出必须是纯 JSON,不要 Markdown 围栏,不要注释。只有时代错位、多个独立目标、非政令或语义不明这四类情况允许输出警告,不得附带其他字段:
{"kind":"clarification","warning_type":"anachronism","message":"沈砚指出此物非大晟所有并请陛下改诏,1-300字"}
{"kind":"clarification","warning_type":"multiple_goals","message":"沈砚请陛下保留本回合最要紧的一个目标,1-300字"}
{"kind":"clarification","warning_type":"not_policy","message":"沈砚说明闲聊、询问或改分要求并非政令,请陛下提出一件要办的事,1-300字"}
{"kind":"clarification","warning_type":"unclear","message":"沈砚说明诏意无法辨认或缺乏治理方向,请陛下重新明诏,1-300字"}

一个明确治理目标可以含配套措施。其余有效输入才结算本回合(三年),输出:
{
  "kind":"accepted",
  "normalized_goal":"用符合大晟时代的白话概括政策目标,忠实玩家原意,自动补全细节,1-200字",
  "tags":["短标签"],
  "policy_intent":{"category":"relief|grain_supply|tax|water|dike|road|military|justice|other等稳定英文类型","region":"适用地区，同一地区不得换同义词","project":"购粮补仓用grain_purchase；其余用具体工程或执行对象的稳定标识","action":"enact|maintain|revoke|suspend|resume","magnitude":"减税未定幅度moderate，减半half，全免full，不再减unchanged，恢复原税额restore，其余unspecified","duration_years":原诏期限年数或null,"prohibitions":["原诏禁止事项"]},
  "policy_effect":{"people":整数,"treasury":整数,"grain":整数},
  "policy_analysis":{"benefits":["谁受益、怎样受益；没有明显公共收益须如实说明，最多3项"],"costs":["已经付出的钱粮、负担、机会成本或受损群体，最多3项"],"risks":[{"condition":"后患出现所需条件，非必然事件","consequence":"可能的负面后果及受影响群体","likelihood":"low|medium|high","horizon":"current|delayed"}],"effect_basis":"用简短因果说明本回合净效果为何如此；潜在风险如何进入后续回声，不能只有口头利弊却仍固定加分"},
  "echo_effects":[{"echo_id":"到期回声id","people":整数,"treasury":整数,"grain":整数,"explanation":"该回声本回合影响说明,1-300字"}],
  "advisor":"沈砚完全以御前辅臣身份向陛下奏对,1-300字",
  "reactions":[{"speaker":"tian_bo|song_zhiyuan|gu_tingzhang","text":"完全以对应古代人物身份、经历和利益说白话,依实际影响自然表达支持、安心、中性看法或担忧,1-300字"}, ...共2至3位且不重复],
  "new_echoes":[{"delay":1或2,"reason":"后续影响说明,1-300字","effect_kind":"已经施行产生的后果用consequence；需要继续拨付钱粮或继续施工用execution"}],
  "summary":"本回合一句话白话总结,1-150字"
}

数值边界:policy_effect 民心 -12 至 +8、国库与粮储各 -20 至 +20;每条 echo_effect 民心 -4 至 +4、国库与粮储各 -10 至 +10。echo_effects 必须恰好覆盖给定的每条到期回声,无到期回声则为空数组。不得输出 policy_id、turn_no、status、最终民心或胜负判断——这些由程序结算。delay 按回合计算,1 为三年后,2 为六年后。进入第八回合时 new_echoes 必须为空;第七回合只允许 delay=1。
"""


def parse_candidate(text: str) -> Candidate:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    try:
        return _candidate_adapter.validate_python(data)
    except Exception as exc:
        raise ValueError(f"模型输出不符合契约: {exc}") from exc


def candidate_to_dict(candidate: Candidate) -> dict:
    if isinstance(candidate, ClarificationCandidate):
        return {
            "kind": "clarification",
            "warning_type": candidate.warning_type,
            "message": candidate.message,
        }
    return {
        "kind": "accepted",
        "normalized_goal": candidate.normalized_goal,
        "tags": candidate.tags,
        "policy_intent": candidate.policy_intent.model_dump(),
        "policy_analysis": candidate.policy_analysis.model_dump(),
        "policy_effect": {
            "people": candidate.policy_effect.people,
            "treasury": candidate.policy_effect.treasury,
            "grain": candidate.policy_effect.grain,
        },
        "echo_effects": [
            {
                "echo_id": e.echo_id,
                "people": e.people,
                "treasury": e.treasury,
                "grain": e.grain,
                "explanation": e.explanation,
            }
            for e in candidate.echo_effects
        ],
        "advisor": candidate.advisor,
        "reactions": [
            {"speaker": r.speaker, "text": r.text} for r in candidate.reactions
        ],
        "new_echoes": [
            {"delay": e.delay, "reason": e.reason, "effect_kind": e.effect_kind} for e in candidate.new_echoes
        ],
        "summary": candidate.summary,
    }
