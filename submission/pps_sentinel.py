"""Static, notice-local evidence-first and re-reading prompt experiments.

The task rules come exclusively from the supplied guidance and CSV. Research
motivates the reading procedure, not any new legal rule or label.
"""
from copy import deepcopy
import hashlib
import json


FACT_ORDER = (
    'law', 'price_basis', 'price', 'small_quotation',
    'product_basis', 'product_kind',
    'direct_production_e', 'direct_production_required',
    'enterprise_e', 'enterprise_scope',
    'exception_basis', 'nonprofit_exception', 'special_sme_exception',
    'performance_e', 'performance_required', 'joint_e', 'joint_mode',
    'minimum_share_percent', 'software_project', 'software_restriction_notice',
)

PRODUCT_READING = '''[사실을 결정하기 전 원문 대조]
product_basis에는 실제 주과업/납품대상과 CSV 적용조건의 충족/불충족 이유를 먼저 쓴 다음 product_kind를 정한다. 직생증명서나 업종등록의 이름은 실제 구매 대상과 일치하는지 별도로 확인한다. 예를 들어 연구조사 용역이 행사 또는 SW 증명서를 요구해도 연구 자체가 행사/SW 구매로 바뀌지는 않는다. 경쟁제품 여부를 서류의 요구/미요구로 역추론하지 않는다.
direct_production_e와 enterprise_e에는 실제 참가자격 문장의 SID를 먼저 고르고 의무와 기업범위를 정한다. 확인서의 제출목록·발급 확인절차와 그 확인서를 보유할 의무를 구별한다. 명시된 기업범위가 없으면 메타의 조항호내용으로 보충하지 않는다.
exception_basis에서 실제 소액수의 여부, 중소기업 우선조달계약 예외, 비영리법인 참가 허용, 유찰로 자격확대 여부를 다시 찾고 다음 두 예외 필드를 결정한다. 우선조달 예외 적용이라는 명시가 있는데 no로 쓰지 않는다. 반대로 창업기업 신용평가 가점·비영리 세액정산·법률 제목은 참가자격 예외가 아니다. 비영리 허용은 nonprofit_exception에, 별도의 우선조달 예외는 special_sme_exception에 각각 분리한다. 과업명만 보고 예외를 가정하지 않는다.
원문을 관측하지 못한 사실은 unknown이다. 반대 근거와 인접 문장의 OR/단서까지 읽고 facts를 완성한 후 v를 계산한다.
'''

PREDICATE_READING = '''[요건과 반증을 함께 확인]
각 항목의 reason을 쓰기 전에 (1) 이 공고가 적용 대상인가, (2) 요구하는 행위와 시점이 실제로 존재하는가, (3) 반대 문장·OR 대안·명시 예외가 있는가를 확인한다. reason에는 결정에 필요한 실제 요건과 예외의 대조를 쓴다. 위반이라는 결론을 반복하지 않는다.
v9는 현재 새로 구매하는 대상을 식별한 뒤 모델 지정을 판단한다. 기존 보유품을 설명하는 표, 기존제품 유지관리, 호환 조건은 신규 모델 지정과 구별한다. v19는 발급주체와 입찰 전 소지·제출 의무를 함께 확인한다. v24는 등록값과 본문 값이 같은 개념인지 먼저 맞추고 모순 축을 적는다. 부가세 계산 관계가 맞는다는 사실만으로 나머지 세 축도 일치한다고 결론 내리지 않는다.
'''


def ordered_fact_schema(schema):
    out = deepcopy(schema)
    facts = out['properties']['facts']
    if set(FACT_ORDER) != set(facts['properties']):
        raise ValueError('Evidence-first schema must preserve every fact field')
    facts['required'] = list(FACT_ORDER)
    facts['properties'] = {key: facts['properties'][key] for key in FACT_ORDER}
    return out


def source_id_schema(schema,fmt):
    """Constrain a citation's syntax, still checking its actual source later."""
    out=deepcopy(schema)
    sid={'type':['string','null'],'pattern':r'^s[0-9]{3,6}$','maxLength':7}
    if fmt=='facts':
        for key in ('direct_production_e','enterprise_e','performance_e','joint_e'):
            out['properties']['facts']['properties'][key]=deepcopy(sid)
        out['properties']['e']['items']=deepcopy(sid)
    elif fmt=='reasoned':
        for item in out['properties'].values():
            item['properties']['e']=deepcopy(sid)
    else:
        raise ValueError('Source-ID schema is for facts or reasoned output')
    return out


def augment_prepared(pipeline, prepared):
    mode = pipeline.config.get('sentinel_reading')
    if not mode:
        return prepared
    if mode not in ('reread', 'predicates'):
        raise ValueError('Unknown static reading procedure')
    out = deepcopy(prepared)
    if mode == 'reread':
        from pps_specialists import GROUPS
        criteria = '\n'.join(f'v{i}: {pipeline.guidance[f"v{i}"]["guide"]}'
                             for i in GROUPS[pipeline.group])
        extra = '\n[원문을 읽은 뒤 같은 제공 기준을 다시 대조]\n' + criteria
    else:
        extra = '\n' + (PRODUCT_READING if pipeline.group == 'products' else PREDICATE_READING)
    out['messages'][-1]['content'] += extra + '\n현재 공고의 원문 근거만으로 지정 JSON에 답하라.'
    count = pipeline.runner.count(out['messages'])
    budget = pipeline.config['max_model_len'] - max(pipeline.config['max_output_tokens'], pipeline.config.get('retry_max_tokens',4096)) - 128
    if count > budget:
        # Never lose sources silently or submit an overlong prompt. The caller
        # rebuilds source selection with a smaller character budget.
        return None
    out['prompt_tokens'] = count
    out['prompt_sha256'] = hashlib.sha256(json.dumps(out['messages'],ensure_ascii=False).encode()).hexdigest()
    return out
