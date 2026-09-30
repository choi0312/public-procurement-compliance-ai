"""Semantic facts from the fixed LLM plus explicit provided-rule calculations.

All calculations concern one notice. No labels, identifiers or other notices are
read here. Unknown extracted facts leave the model's original decision intact.
"""
from copy import deepcopy


def enum(*values):
    return {"type":"string","enum":list(values)}


TRI=enum("yes","no","unknown")
EVIDENCE={"type":["string","null"],"maxLength":350}
FACT_PROPERTIES={
    "law":enum("national","local","unknown"),
    "price":{"type":["integer","null"],"minimum":0},
    "price_basis":{"type":"string","maxLength":100},
    "small_quotation":TRI,
    "product_kind":enum("competitive","general","unknown"),
    "product_basis":{"type":"string","maxLength":150},
    "direct_production_required":TRI,
    "direct_production_e":EVIDENCE,
    "enterprise_scope":enum("small_only","sme","unrestricted","unknown"),
    "enterprise_e":EVIDENCE,
    "nonprofit_exception":TRI,
    "special_sme_exception":TRI,
    "exception_basis":{"type":"string","maxLength":100},
    "performance_required":TRI,
    "performance_e":EVIDENCE,
    "joint_mode":enum("joint","separate","none","unknown"),
    "minimum_share_percent":{"type":["number","null"],"minimum":0,"maximum":100},
    "joint_e":EVIDENCE,
    "software_project":TRI,
    "software_restriction_notice":TRI,
}
FACT_SCHEMA={"type":"object","additionalProperties":False,
             "required":list(FACT_PROPERTIES),"properties":FACT_PROPERTIES}

FACT_INSTRUCTIONS="""
이 과제의 1은 제공 판정 조건이 성립한다는 분류값이다. 일반적 법률상식이나 재량·통상 적정성으로 주어진 조건을 변경하지 않는다.
최종 v를 정하기 전에 facts에 현재 문서의 사실을 독립적으로 추출한다. 적법/위법 결론을 facts에 대신 쓰지 않는다.
- law: 적용계약법 national/local/unknown. price: 이번 발주의 VAT제외 추정가격(원)이며 요구하는 과거실적액과 다르다. 본문명시값 우선, 없으면 meta. price_basis에 출처와 금액을 짧게 적는다.
- small_quotation: 실제 소액수의 견적입찰인지 yes/no/unknown. 저액·긴급·협상만으로 yes가 아니다.
- product_kind: 실제 구매 대상과 제공 경쟁제품 CSV의 조건을 비교한 competitive/general/unknown. 증명서 품명만으로 실제 구매 대상을 바꾸지 않는다. 단순 키워드 미검색이나 CSV 특이사항 불확실은 unknown이다. 실제 구매품목이 확인되고 그 정확한 품명코드가 완전한 제공 CSV에 없다는 조회는 general의 근거가 될 수 있다. product_basis에 실제 대상과 CSV 조건을 적는다. 이 공고의 v10~18은 이 동일한 분류를 사용한다.
- direct_production_required: 참가자격으로 직접생산확인증명서를 반드시 소지해야 하는지 yes/no/unknown. 서류목록/확인 절차만 있고 참가자격이 없으면 no. direct_production_e에 해당 원문 구간ID를 적는다.
- enterprise_scope: 비영리법인의 추가 허용을 제외한 영리기업의 참가범위다. 소기업·소상공인만이면 small_only, 중기업도 포함한 중소기업이면 sme, 기업규모를 제한하는 자격이 없으면 unrestricted, 알 수 없으면 unknown. '소기업 또는 비영리법인'은 small_only, '중소기업 또는 비영리법인'은 sme다. 제목·등록메타·제출서류 목록만으로 자격 제한을 만들지 않는다. 중소기업은 소기업보다 넓다. enterprise_e는 자격제한 원문 구간ID.
- nonprofit_exception: 판로지원법 시행령2조의3에 따라 비영리법인의 입찰 참가를 명시 허용하는 해당 연구·교육 등 예외가 있으면 yes, 없으면 no, 관측 불가면 unknown. 비영리법인의 면세·이윤공제 정산문구는 참가예외가 아니므로no. special_sme_exception: 위 비영리 예외를 제외하고 적법한 유찰·소기업 부족 확대, 법정 공동사업·창업·벤처, SW금액별 참여제한 등 기업규모 제한의 별도 명시된 예외면yes, 없으면no. 일반 '중소기업기본법' 인용이나 과업 제목만은 예외가 아니다. exception_basis에 실제 예외를 적는다.
- 실제 competitive SW의 통상 사업금액별 참여제한은 product_kind의 분류조건이며 special_sme_exception=no이다. general인 실제 SW사업에서 중소기업 제한의 별도 근거로 적용되는 참여제한은 special_sme_exception=yes로 하고 그 사실을 exception_basis에 쓴다.
- performance_required: 과거 납품·수행실적을 필수 참가자격으로 요구하는지 yes/no/unknown. 평가가점·서류목록만은 no. performance_e는 해당 자격 구간ID.
- joint_mode: 공동이행 joint / 분담이행 separate / 공동계약불가 none / unknown. minimum_share_percent: 구성원 최소 지분율 숫자, 미기재면null. joint_e는 해당 원문 구간ID.
- software_project: 실제 과업이 SW사업인지 yes/no/unknown. 업종코드 단어만으로 확정하지 않는다. software_restriction_notice: 해당 SW 사업금액별 대기업 참여제한 또는 관련 SW48조 안내가 있는지 yes/no/unknown. 일반 중소기업 자격만은 이 안내가 아니다.
출력은 {"facts":{위 필드 전부},"v":[v1..v24의 정수24개],"e":[e1..e24의24개]} JSON이다. 먼저 관측 사실을 채우고 그 사실에 주어진 조건을 적용한다.
"""


def schema(compact_schema):
    out=deepcopy(compact_schema)
    out["required"]=["facts","v","e"]
    out["properties"]={"facts":FACT_SCHEMA,**out["properties"]}
    return out


def validate_facts(facts):
    if not isinstance(facts,dict) or set(facts)!=set(FACT_PROPERTIES):
        raise ValueError("Missing or extra semantic fact fields")
    for key,spec in FACT_PROPERTIES.items():
        value=facts[key]
        if "enum" in spec:
            if value not in spec["enum"]:raise ValueError("Invalid categorical fact: "+key)
            continue
        types=spec["type"] if isinstance(spec["type"],list) else [spec["type"]]
        if value is None and "null" in types:continue
        if "string" in types:
            if not isinstance(value,str) or len(value)>spec.get("maxLength",10**9):raise ValueError("Invalid string fact: "+key)
        elif "integer" in types or "number" in types:
            valid=type(value) is int if "integer" in types else type(value) in (int,float)
            if not valid or not spec.get("minimum",0)<=value<=spec.get("maximum",10**15):raise ValueError("Invalid numeric fact: "+key)


def apply_facts(obj,rec=None,evidence_validator=None):
    """Apply the provided v10–18 truth table to explicit, known LLM facts.

    Sources: provided item table; Product Purchase Act9, Enforcement Decree2-2,
    2-3,7,10; competitive-product CSV and its conditions; official Q&A417282.
    Actual small quotations and separately justified SME exceptions abstain.
    A nonprofit participation exception only excuses missing restrictions; it
    does not legalize overly narrow/wide restrictions on for-profit firms.
    """
    if "facts" not in obj:return obj,[]
    f=obj["facts"];validate_facts(f)
    if rec is not None:
        scope=str((rec.get("meta") or {}).get("업무구분", ""))
        if "공사" in scope or not any(x in scope for x in ("물품","용역")):return obj,[]
    kind=f["product_kind"]
    out=deepcopy(obj);changes=[]
    def set_value(i,value,evidence=None,rule=""):
        old=out["v"][i-1];value=int(value)
        out["v"][i-1]=value
        if not value or i in {10,11,16,18}:out["e"][i-1]=None
        else:out["e"][i-1]=evidence
        if old!=value:changes.append({"item":f"v{i}","before":old,"after":value,"rule":rule})
    direct=f["direct_production_required"];scope=f["enterprise_scope"]
    if evidence_validator is not None:
        if direct=="yes" and not evidence_validator(f["direct_production_e"]):direct="unknown"
        if scope in {"small_only","sme"} and not evidence_validator(f["enterprise_e"]):scope="unknown"
    # Explicit qualifications disprove their absence even when a procurement
    # exception prevents a positive decision. These are logical prerequisites,
    # not an assumption that every exempt tender is compliant.
    if direct=="yes":set_value(10,0,rule="explicit required certificate disproves its absence")
    if scope in {"small_only","sme"}:
        for i in (11,16,18):set_value(i,0,rule="explicit enterprise qualification disproves absence")
    if scope=="sme":
        for i in (13,15):set_value(i,0,rule="medium enterprises are included")
    if scope=="small_only":set_value(17,0,rule="medium enterprises are excluded")
    if scope=="unrestricted":
        for i in (13,14,15,17):set_value(i,0,rule="no affirmative enterprise-size restriction")
    if kind=="general":
        for i in (10,11,13):set_value(i,0,rule="general product: competitive branch inapplicable")
    if kind=="competitive":
        for i in (12,14,15,16,17,18):set_value(i,0,rule="competitive product: general branch inapplicable")
    if f["small_quotation"]!="no" or f["special_sme_exception"]!="no" or kind=="unknown":return out,changes
    if kind=="competitive":
        for i in (12,14,15,16,17,18):set_value(i,0,rule="competitive product: general-product branch inapplicable")
        if direct!="unknown":set_value(10,direct=="no",rule="competitive product requires direct-production qualification")
        if scope!="unknown":
            set_value(11,scope=="unrestricted",rule="competitive product requires SME qualification")
            set_value(13,scope=="small_only",f["enterprise_e"],"competitive product must not exclude medium enterprises")
        return out,changes
    for i in (10,11,13):set_value(i,0,rule="general product: competitive-product branch inapplicable")
    if direct!="unknown":set_value(12,direct=="yes",f["direct_production_e"],"general product cannot require direct-production certificate")
    price=f["price"]
    if price is None or price<=0 or scope=="unknown":return out,changes
    for i in (14,15,16,17,18):
        # Missing-qualification decisions require a known exception state.
        missing_candidate=(scope=="unrestricted" and (i==16 and 100_000_000<=price<230_000_000 or i==18 and price<100_000_000))
        if missing_candidate and f["nonprofit_exception"]=="unknown":continue
        hit=(i==14 and price>=230_000_000 and scope in {"small_only","sme"}
             or i==15 and 100_000_000<=price<230_000_000 and scope=="small_only"
             or i==16 and 100_000_000<=price<230_000_000 and scope=="unrestricted" and f["nonprofit_exception"]=="no"
             or i==17 and price<100_000_000 and scope=="sme"
             or i==18 and price<100_000_000 and scope=="unrestricted" and f["nonprofit_exception"]=="no")
        set_value(i,hit,f["enterprise_e"],"general-product price and enterprise-scope truth table")
    return out,changes
