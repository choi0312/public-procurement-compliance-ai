"""Source-role isolation and complete-clause retrieval for one notice.

Experimental options are disabled unless explicitly selected in config.
No evaluation labels, notice-ID rules, or cross-notice state are used.
"""
from copy import deepcopy
import hashlib
import json
import re

import pps_io as io
from pps_context import formatted_context

ROLE_INSTRUCTIONS = """
[출처와 논리의 분리]
등록 meta는 본문과 대조할 보조 정보다. meta의 조항호내용·기업규모 설명·업종 등록이 본문의 실제 참가자격을 대신하지 않는다.
직접생산 증명서 소지와 중소기업 확인서 소지는 별개 조건이다. 직생 소지가 있다고 중소기업 자격 문장이 있다고 추론하지 않는다.
법령 제목 속 '중소기업'은 참가할 기업의 범위가 아니다. 제8조의2의 부정참여 배제 안내도 기업규모 제한 문구가 아니다.
원문에서 실제 명령의 주체·행위·시점·예외를 확인한다. 제출서식의 빈칸과 목록, 이행 중 준수사항, 과거 실적과 보유 장비 현황을 현재 참가자격으로 바꾸지 않는다.
원문이 요구하지 않은 조건을 meta나 상식으로 채우지 않는다. 반대로 관측한 실제 제한을 막연히 통상적이라는 이유로 면제하지 않는다.
"""
CHECKLISTS = {
    'qualification': """
[자격 조항의 논리 확인]
v1: 일반 영리기업도 참가 가능한 기본 자격에 비영리법인·대학을 '추가로' 허용한 것은 기관 한정이 아니다. '대학 또는 연구기관만'처럼 다른 사업자를 배제한 경우와 구별한다. '컨설팅기관/관련 전문업체'가 일반 사업자에게 열린 표현인지 확인한다.
시설·인력은 법정 등록기준 자체 또는 해당 법령에 따른 시설 확인인지, 별도의 근거 없는 추가 사전보유 조건인지 구분한다. 단순 장비현황 제출, 이행시 배치계획, 납품시 사후관리 의무만으로 추가 사전보유 제한을 만들지 않는다. 식품·폐기물 등 분야 이름만으로 예외를 만들지는 않는다.
v2~4,8: 실적이 실제 참가 필수자격인지 먼저 확인하고, 해당되는 금액/배수/발주기관 한정/지역 동시제한을 각각 판정한다. 과거실적 R, 이번 가격 P, 이번 예산 B를 별개 숫자로 읽는다.
v9: 신규 납품의 특정 상표·모델 지정인지, 기존 자산의 유지보수·라이선스 갱신 또는 명시된 호환성 유지인지 확인한다. 모델 지정과 동등이상 허용 문장을 모두 읽는다. 일반 규격 숫자는 모델명이 아니다. 막연한 호환성 면제도, 모델 문자만 발견하고 무조건 위반으로 하는 것도 피한다.
""",
    'products': """
[제품 판단 순서]
1 실제 계약의 주된 산출물/서비스를 공고 건명과 과업에서 확인한다. 실제 대상 이름과 직접생산증명서에 붙은 품명은 다를 수 있다. 일반 연구·교육/운영에 행사/SW 증명서만 요구한 것을 행사/SW 구매로 바꾸지 않는다.
2 제공 CSV의 정확한 품명과 특이사항을 확인한다. '운영위탁서비스'는 문맥상 SW 정보시스템 운영이며 모든 위탁용역을 뜻하지 않는다. 간장·컴퓨터서버·경비 등 제한조건은 코드가 있다고 자동 충족하지 않는다.
3 참가자격의 기업범위와 직접생산 소지를 각각 추출한다. 중소기업이라는 법률명, 등록 meta, 제출목록만으로 자격 소지를 만들어내지 않는다. 자격 문장의 '중소기업/중·소기업'과 '소기업'을 구별한다.
4 원문이 소액수의 견적이라고 명시하면 메타의 제한경쟁 표기와 혼동하지 않는다. 수의 예외·비영리 참가 예외·우선조달 예외는 실제 명시 문구가 있는지 확인한다. 단순 면세 정산 문구는 참가 예외가 아니다.
5 facts를 먼저 완성하고 한 가지 일관된 실제제품 분류·금액·기업범위로 v10~18을 계산한다. 직생만 있고 중소기업 자격이 빠진 경우 두 사실을 독립적으로 유지한다.
""",
    'procedure': """
[절차 판단의 필수요건]
v19: 누가 발급하는 무슨 문서인지와 제출시점을 함께 확인한다. 제조사/공급자의 물품공급 또는 기술지원 확약서를 입찰자가 입찰/제안 마감 전에 얻도록 하는 조건을 탐지한다. 입찰자가 스스로 서명하는 이행·보증 각서, 제품규격 확인자료, 일반 파트너 등록증이나 낙찰 후 제출만으로 공급확약서 입찰전 제출을 만들어내지 않는다.
v20: 실제 SW 과업인지 먼저 확인한다. SW 문구·코드가 없는 실제 SW사업도 놓치지 말고, 비SW 구매/용역이면 SW공통서식만으로 사업을 바꾸지 않는다.
v21~23: 공동이행/분담이행, 구성원 최소지분율, 설명회 참석의 의무성, 실제 공고일부터 실제 설명회까지의 날짜를 구분한다. 제안평가회·업체가 선정되는 설명회는 입찰참가 필수 현장설명과 다르다.
v24: 예산/계약방법/지역/업종의 네 축을 각각 비교한다. 한 축의 명백한 모순이면 나머지가 같아도1이다. VAT 차이·총액/단가 차이·제한경쟁/협상 차이는 동종 비교 후 판단한다. 빈 목록만으로 모순을 만들지 말되 meta의 명시 N과 실제 본점/업종 제한이 있으면 대조한다. OR와 AND를 구별한다.
""",
}


def role_record(rec,group):
    out=deepcopy(rec)
    if group=='products':
        # A registration description is not evidence of actual SME wording.
        # Preserve explicit exception descriptions, which the supplied rules
        # allow as a separate source; remove only an affirmative SME label.
        raw=str(out.get('meta',{}).get('조항호내용') or '')
        if re.search(r'중소기업|중기업|소기업|소상공인',raw) and not re.search(r'예외|유찰|창업|벤처|공동사업',raw):
            out['meta'].pop('조항호내용',None)
    return out


def docket_spans(rec,group,max_chars):
    from pps_specialists import select_domain_spans
    from pps_qualification_facts import _sections
    spans=[];covered={};used=0
    def add(di,start,end):
        nonlocal used
        if used>=max_chars:return
        start=max(0,start);end=min(len(rec['docs'][di]['text']),end)
        pending=[(start,end)]
        for a,b in covered.get(di,[]):
            nxt=[]
            for x,y in pending:
                if y<=a or x>=b:nxt.append((x,y))
                else:
                    if x<a:nxt.append((x,a))
                    if y>b:nxt.append((b,y))
            pending=nxt
        for x,y in pending:
            y=min(y,x+max_chars-used)
            if x>=y:continue
            covered.setdefault(di,[]).append((x,y));used+=y-x
            while x<y:
                finish=min(x+450,y)
                if finish<y:
                    boundary=rec['docs'][di]['text'].rfind('\n',x+300,finish)
                    if boundary>=x+300:finish=boundary+1
                doc=rec['docs'][di]
                spans.append({'sid':f's{len(spans)+1:03d}','doc_id':doc['doc_id'],'type':doc['type'],'start':x,'end':finish,'text':doc['text'][x:finish]})
                x=finish
    # Complete participant sections receive priority over scattered keyword
    # matches, so AND/OR and following waivers stay observable.
    for di,d in enumerate(rec['docs']):
        if d['type']=='공고문':add(di,0,min(1000,max_chars//6))
    allowance=min(int(max_chars*.57),8500)
    for di,d in enumerate(rec['docs']):
        if d['type']!='공고문':continue
        for sec in _sections(d['text']):
            if used>=allowance:break
            add(di,max(0,sec['start']-90),min(sec['end']+180,sec['start']+allowance-used))
    if group=='procedure':
        patterns=r'공급.{0,8}확약|기술지원.{0,8}확약|공동.{0,8}이행|지분율|설명회|현장설명|참여.{0,6}제한'
        for di,d in enumerate(rec['docs']):
            for m in re.finditer(patterns,d['text']):
                if used>=max_chars*.75:break
                add(di,m.start()-180,m.end()+260)
    for span in select_domain_spans(rec,group,max_chars):
        di=next(i for i,d in enumerate(rec['docs']) if d['doc_id']==span['doc_id'] and d['text'][span['start']:span['end']]==span['text'])
        add(di,span['start'],span['end'])
    return spans


def prepare_frontier(pipeline,rec):
    group=pipeline.group;cfg=pipeline.config;mode=cfg['frontier_mode']
    if mode not in {'roles','docket'}:raise ValueError('Unknown frontier mode')
    view=role_record(rec,group)
    system=pipeline.system+ROLE_INSTRUCTIONS
    if mode=='docket':system+=CHECKLISTS[group]
    budget=cfg['max_model_len']-max(cfg['max_output_tokens'],cfg.get('retry_max_tokens',4096))-128
    max_chars=cfg['document_chars']
    if mode=='roles':
        base=pipeline._prepare_standard(view)
        messages=deepcopy(base['messages']);messages[0]['content']=system
        count=pipeline.runner.count(messages)
        if count<=budget:
            return {**base,'messages':messages,'prompt_tokens':count,'prompt_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest()}
        # A longer instruction can exceed the limit; use bounded source-aware
        # preparation rather than silently sending an oversized prompt.
    refs=pipeline.facts.numeric_bands(view)
    if group=='products':
        refs+='\n'+pipeline.facts.describe(view)+'\n'+pipeline.facts.code_membership(view)
        if cfg.get('actual_fields_context'):
            from pps_product_facts import _actual_fields
            fields=_actual_fields(rec)
            primary=[v for v in fields if v['type']=='공고문']
            refs+='\n[현재 실제 구매/용역 필드 원문; 요구하는 증명서 품명과 별개]\n'+json.dumps([{'doc_id':v['doc_id'],'text':v['text'][:260]} for v in (primary or fields)[:8]],ensure_ascii=False)
        from pps_qualification_facts import extract_qualification_facts
        q=extract_qualification_facts(rec)
        refs+='\n[현재 공고문 자격 구문 분석; unknown은 미확정이며 검색 실패가 곧 부재는 아님]\n'+json.dumps({k:q[k] for k in ('direct_production_required','direct_production_e','enterprise_scope','enterprise_e')},ensure_ascii=False)
    if group=='procedure':
        from pps_metadata_rules import metadata_assessment
        refs+='\n[현재 원문과 meta의 네 축 문자 대조; 자동 추출 후보이므로 의미와 예외를 원문 재확인]\n'+json.dumps(metadata_assessment(rec),ensure_ascii=False)
    for _ in range(15):
        spans=docket_spans(rec,group,max_chars)
        user='[현재 공고 등록 보조정보; 실제 참가자격 원문이 아님]\n'+io.format_meta(view)+'\n\n[제공 자료 조회와 현재 공고의 문자 대조]\n'+refs
        user+='\n\n[현재 공고 원문; 같은 문서의 인접 SID는 이어지는 문맥]\n'+formatted_context(spans)
        user+='\n\n위 원문에서 요건의 존재/부재와 적용 예외를 구별해 지정 JSON으로 답하라. 등록정보를 실제 자격문장으로 인용하지 않는다.'
        messages=[{'role':'system','content':system},{'role':'user','content':user}]
        count=pipeline.runner.count(messages)
        if count<=budget:
            return {'messages':messages,'spans':spans,'prompt_tokens':count,'document_chars':max_chars,'prompt_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest()}
        if max_chars<=2500:raise RuntimeError('Frontier source prompt does not fit')
        max_chars=max(2500,int(max_chars*min(.8,.9*budget/count)))
    raise RuntimeError('Frontier prompt budget did not converge')
