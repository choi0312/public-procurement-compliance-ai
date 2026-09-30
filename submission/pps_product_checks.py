"""Bounded item reasons between current-notice facts and final decisions."""
from copy import deepcopy
import hashlib
import json

KEYS=[f'v{n}' for n in range(10,19)]


def checks_schema(base):
    out=deepcopy(base)
    checks={'type':'object','required':KEYS,'additionalProperties':False,
            'properties':{key:{'type':'string','maxLength':60} for key in KEYS}}
    props=out['properties'];out['required']=['facts','checks','v','e']
    out['properties']={'facts':props['facts'],'checks':checks,'v':props['v'],'e':props['e']}
    return out


def strip_checks(obj):
    if not isinstance(obj,dict) or set(obj)!={'facts','checks','v','e'}:
        raise ValueError('Missing bounded product checks')
    checks=obj['checks']
    if not isinstance(checks,dict) or set(checks)!=set(KEYS):raise ValueError('Missing product item check')
    if any(not isinstance(v,str) or len(v)>60 for v in checks.values()):raise ValueError('Invalid bounded item check')
    return {k:obj[k] for k in ('facts','v','e')}


def parse_checked(text,selected=None):
    from script import parse_result
    import pps_io
    obj=pps_io.extract_json(text)
    if not isinstance(obj,dict):raise ValueError('Product response must be an object')
    if set(obj)=={'v','e'}:return parse_result(text,selected)
    return parse_result(json.dumps(strip_checks(obj),ensure_ascii=False),selected)


def augment_prepared(prepared,runner,config):
    out=deepcopy(prepared)
    out['messages'][-1]['content']+='''
추가 출력 순서: facts를 먼저 추출하고 checks에 v10~v18 각각의 판단 이유를 쓴 뒤 기존 v/e 배열을 결정한다.
checks는 v10,v11,v12,v13,v14,v15,v16,v17,v18 키를 갖는 객체이며 각 값은 60자 이내의 짧은 문자열이다.
각 이유에서 실제 제품 분기, 금액 구간, 관측 자격/부재, 명시 예외 중 그 항목의 결정 조건을 대조한다. 다른 항목의 결론을 복제하지 않는다.
facts와 이유가 모순되면 현재 원문과 해당 검토 기준을 다시 대조한다. 최종 JSON의 키는 facts,checks,v,e이다. v와 e는 기존처럼 각각24개다.
'''
    out['prompt_tokens']=runner.count(out['messages'])
    budget=config['max_model_len']-max(2048,config['max_output_tokens'],config.get('retry_max_tokens',0))-128
    if out['prompt_tokens']>budget:return None
    out['prompt_sha256']=hashlib.sha256(json.dumps(out['messages'],ensure_ascii=False).encode()).hexdigest()
    return out
