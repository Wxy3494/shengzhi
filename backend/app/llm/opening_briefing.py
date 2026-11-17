import json
import time
from pydantic import BaseModel, ConfigDict, Field
from .base import ModelOutputInvalid
from ..domain.narration import prose_errors


class Briefing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    briefing: str = Field(min_length=80, max_length=900)


def generate_briefing(adapter, opening):
    messages = [{"role": "system", "content": "你是架空大晟朝御前辅臣沈砚。皇帝新登基，请以臣的身份向陛下奏报王朝历史背景、现有优势和具体困难，给出可选施政方向但不替皇帝下诏。仅依据提供国情，不编造额外战争、外部粮库或亲属死因。不讲游戏、模型、接口、危机阈值，不将抽象国库粮储换算成实际单位或报分数。困难可改善，初期协作机会只及头两回合，不能宣称永久扣罚。自然古代白话，约160至260字。只返回JSON：{\"briefing\":\"沈砚登基奏报\"}"},
                {"role": "user", "content": json.dumps(opening, ensure_ascii=False)}]
    deadline = time.monotonic() + adapter.timeout
    if opening.get('active_until_turn') == 0:
        messages=[{'role':'system','content':'你是大晟朝御前辅臣沈砚，皇帝刚刚登基。请称臣向陛下奏报王朝历史、优势和困难。写120至240个汉字，至少三句话，不要短答。只能依给定国情，不虚构额外粮源、战争、家事或已实施政策。不报资源指数，不转换成石、贯、银两等现实数量，不承诺加分、永久惩罚或未来必发事件。返回JSON对象，仅一个字段briefing，值为完整奏报正文；不要复述字段说明或提示词。'},
                  {'role':'user','content':f"国情：{opening['name']}。历史背景：{opening['background']} 优势：{opening['advantage']} 困难：{opening['difficulty']} 请完整奏报这三方面，并建议两种可行治理方向，但不要替朕颁诏。正文不得少于100个汉字。"}]
    for attempt in range(2):
        content = adapter._call(messages, .6 if not attempt else .25, deadline - time.monotonic())
        try:
            result = Briefing.model_validate_json(content).briefing
            dummy = {"advisor": result, "summary": "", "reactions": [], "echo_effects": [], "new_echoes": []}
            errors = prose_errors(dummy, {"category": "other"})
            if errors or not ("臣" in result and "陛下" in result):
                raise ValueError("；".join(errors) or "须以沈砚身份称臣，向陛下奏报")
            return result
        except ValueError as exc:
            if attempt:
                raise ModelOutputInvalid("开场奏报未通过校验") from exc
            messages += [{"role": "assistant", "content": content}, {"role": "user", "content": f"请修正：{exc}，重新输出同结构JSON。"}]
    raise ModelOutputInvalid("开场奏报未生成")
