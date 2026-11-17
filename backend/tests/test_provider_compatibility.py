"""Known Qwen spelling/name variants do not relax numerical or state authority."""
import json

import pytest

from app.llm.schema import parse_candidate,candidate_to_dict
from conftest import make_accepted


def test_legacy_chinese_roles_and_misspelled_new_echoes_preserve_values():
    expected=candidate_to_dict(make_accepted(policy_effect={'people':4,'treasury':-2,'grain':1},
        new_echoes=[{'delay':1,'reason':'休养后的民生变化'}]))
    raw=json.loads(json.dumps(expected))
    for role,name in zip(raw['reactions'],['田伯','顾廷章']): role['speaker']=name
    raw['new_echoffects']=raw.pop('new_echoes')
    assert candidate_to_dict(parse_candidate(json.dumps(raw)))==expected


def test_unknown_character_is_still_rejected():
    raw=make_accepted().model_dump();raw['reactions'][0]['speaker']='未知人物'
    with pytest.raises(ValueError): parse_candidate(json.dumps(raw))


def test_variant_does_not_allow_state_injection():
    raw=make_accepted().model_dump();raw['new_echoffects']=raw.pop('new_echoes')
    raw['stateDelta']={'people':99}
    with pytest.raises(ValueError): parse_candidate(json.dumps(raw))


def test_conflicting_correct_and_variant_fields_are_rejected():
    raw=make_accepted().model_dump();raw['new_echoffects']=[{'delay':2,'reason':'额外后果'}]
    with pytest.raises(ValueError): parse_candidate(json.dumps(raw))


def test_misspelled_echo_still_obeys_inner_schema():
    raw=make_accepted().model_dump();raw['new_echoffects']=raw.pop('new_echoes')
    raw['new_echoffects']=[{'delay':1,'reason':'后果','stateDelta':{'people':99}}]
    with pytest.raises(ValueError): parse_candidate(json.dumps(raw))


def test_qwen_legacy_proposal_repairs_semantics_without_numeric_relaxation():
    from app.llm.live import LiveAdapter
    from app.llm.base import ModelContext
    analysis={'benefits':['减轻民间负担'],'costs':['库收有所减少'],'risks':[],'effect_basis':'温和减征，兼顾民生与财政。'}
    raw=make_accepted(policy_effect={'people':4,'treasury':-2,'grain':0},policy_analysis=analysis).model_dump()
    for key in ('advisor','summary','reactions'):raw.pop(key)
    bad={**raw,'policy_effect':{'people':99,'treasury':-2,'grain':0}}
    replies=iter([json.dumps(bad),json.dumps(raw)]);seen=[]
    adapter=LiveAdapter('unused','unused','qwen-flash-character')
    def call(messages,*args):
        seen.append(messages[-1]['content']);return next(replies)
    adapter._call=call
    context=ModelContext(game={'schema_version':2,'people':50,'treasury':60,'grain':60},turn_no=1,period='承和元年至三年',player_policy='休养生息')
    result=adapter.evaluate(context)
    assert result.policy_effect.people==4 and len(seen)==2
    assert result.advisor=='待结算后奏对。'
    assert context.game['schema_version']==2


def test_risk_language_aliases_preserve_only_known_enums():
    from app.llm.schema import PolicyRisk
    risk=PolicyRisk(condition='若供给不足',consequence='可能延误',likelihood='中等',horizon='延迟')
    assert risk.likelihood=='medium' and risk.horizon=='delayed'
    with pytest.raises(ValueError): PolicyRisk(condition='若供给不足',consequence='可能延误',likelihood='必然',horizon='延迟')
