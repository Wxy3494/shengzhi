import json
from pathlib import Path

import pytest

from app.domain.narration import prose_errors


def prose(text):
    return dict(advisor=text,summary='',reactions=[],echo_effects=[],new_echoes=[])


@pytest.mark.parametrize('sentence',[
    '温和减征而非全免，仍征收一部分。',
    '减征非全免，州县仍须征收一部分。',
    '并非全免，仍照常征收一部分。',
    '不是全免。','并不全免。','没有全免。','绝非全免。',
    '未全部免除。','不得全免。','不予免征。',
])
def test_single_denial_does_not_claim_exemption(sentence):
    assert not prose_errors(prose(sentence),{'category':'tax','magnitude':'moderate'})


@pytest.mark.parametrize('sentence',[
    '全部免除田赋。','各州一律免税。','本次全免。',
    '非全免之说不确，实际全免。',
    '并非不全免。','不是不免税。',
    '并非全免，但免除田赋。',
])
def test_affirmation_and_double_negation_still_rejected(sentence):
    assert prose_errors(prose(sentence),{'category':'tax','magnitude':'moderate'})


def test_saved_reproduction_no_longer_false_positive():
    from app.llm.schema import NarrationModel
    path=Path(__file__).resolve().parents[2]/'docs/evidence/narration-diagnosis-20261106.json'
    report=json.loads(path.read_text(encoding='utf8'))
    narrative=NarrationModel.model_validate_json(report['repeat_provider_outputs'][-1])
    data={**narrative.model_dump(),'echo_effects':[], 'new_echoes':[]}
    assert not prose_errors(data,report['settled_facts']['intent'])
