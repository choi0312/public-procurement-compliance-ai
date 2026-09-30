"""Positive-only regional corrections from supplied law, scoped to one notice.

No model, label, notice identifier, cross-notice state, or external lookup is
used. Missing/ambiguous facts abstain; they never produce a zero decision.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re

from pps_region import extract_region_qualifications, PROVINCE_RE
from pps_rules import _contract_facts, effective_price, qualification_evidence


NATIONAL_LIMIT=Decimal("230000000")
LOCAL_SAFE_LIMIT=Decimal("500000000")
PROVENANCE={
    "v5":["항목표.json v5", "국가를 당사자로 하는 계약에 관한 법률 시행규칙 제24조",
          "지방자치단체를 당사자로 하는 계약에 관한 법률 시행규칙 제24조"],
    "v6":["항목표.json v6", "국가를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제3항",
          "지방자치단체를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제3항"],
    "v7":["항목표.json v7", "국가를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제3항",
          "지방자치단체를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제3항·제5항·제6항"],
    "v8":["항목표.json v8", "국가를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제5항",
          "지방자치단체를 당사자로 하는 계약에 관한 법률 시행규칙 제25조제7항"],
}
_TECHNICAL=re.compile(r"건설기술|건설사업관리|엔지니어링|(?:설계|시공)\s*감리|안전점검|정밀안전진단")
_COUNT_EXCEPTION=re.compile(
    r"(?:유자격|자격.{0,30}(?:갖춘|보유|업체)|해당지역.{0,20}업체|참여가능업체)"
    r".{0,65}(?:(?:10|십)(?:인|명|개사|개업체|업체)?미만|[1-9](?:인|명|개사|개업체)(?:뿐|에불과))"
)
_SITE=re.compile(r"납품(?:지|장소)|(?:공사|사업|용역)현장|사업지역|수행지역|과업대상지역|대상시설")
_ACTUAL_CROSSING=re.compile(r"걸쳐|걸치|분산|여러|복수|2개이상|둘이상")
_JOIN=re.compile(r"또는|및|[,·ㆍ/]|(?:와|과)\s*")
_OPEN_REGION=re.compile(
    r"(?:한정|제한)(?:하지않|하지아니|이없|은없|을두지)|"
    r"다른지역.{0,25}(?:업체|기업).{0,20}(?:참가|참여).{0,15}(?:가능|수있)|"
    r"전국(?:의|모든)?(?:업체|기업).{0,25}(?:참가|참여)"
)
_ALTERNATIVE_CONDITIONS=re.compile(
    r"(?:다음|아래).{0,80}(?:중|에서)(?:어느)?하나(?:만|이상)?|"
    r"(?:가목|가항).{0,30}(?:나목|나항).{0,30}(?:중하나|택일|선택)"
)
_TERSE_BASIC_QUALIFICATION=re.compile(r"지역\s*(?:업체|기업)\s*[.。]?\s*$")
_TERSE_NONMANDATORY=re.compile(r"우대|우선|가점|권장|선호|비율|평가|가능|지원\s*대상")
_ALTERNATE_QUALIFICATION_TITLE=re.compile(
    r"(?:공모\s*[·ㆍ‧/및]+\s*입찰|입찰\s*[·ㆍ‧/및]+\s*공모|입찰\s*\(\s*응모\s*\))\s*참가\s*자격"
)


def _texts(rec):
    return [d for d in rec.get("docs",[]) if isinstance(d,dict) and isinstance(d.get("text"),str)]


def _compact(text):
    return re.sub(r"\s+","",text)


def _amounts(rec):
    price=effective_price(rec)
    if not price["reliable"]:return []
    values=[Decimal(x["amount"]) for x in price["body_estimates"]]
    if price["meta_amount"] is not None:values.append(Decimal(price["meta_amount"]))
    return values


def _explicit_quotation(rec):
    # A metadata competitive-method flag cannot overrule a current notice's
    # explicit quotation title or labelled negotiated-contract method.
    for doc in _texts(rec):
        if doc.get("type")!="공고문":continue
        intro=doc["text"][:3000]
        if re.search(r"(?m)^[^\n]{0,45}수의\s*(?:계약)?[^\n]{0,25}(?:견적|안내\s*공고)",intro[:650]):return True
        if re.search(r"계약방법[:：]?수의(?:\(|계약|총액|단가|견적)",_compact(intro)):return True
    return False


def _province_names(text):
    # Only literal province names and supplied anonymization attributes.
    return set(PROVINCE_RE.findall(text)) | set(re.findall(r"\|광역=([^|\]]+)",text))


def _explicit_region_exception(rec):
    """Detect an explicit supplied exception; mere adjacency is not enough."""
    actual_site_provinces=set()
    for doc in _texts(rec):
        text=doc["text"]
        compact=_compact(text)
        if _COUNT_EXCEPTION.search(compact):return True
        if "공동혁신도시" in compact:return True
        if re.search(r"(?:시[·ㆍ]?도|광역).{0,45}(?:신설|설치|통합).{0,50}3년",compact):return True
        for paragraph in re.split(r"\n\s*\n",text):
            block=_compact(paragraph)
            for match in _SITE.finditer(block):
                window=block[match.start():match.end()+220]
                window=re.split(r"입찰참가자격|참가자격|법인등기부|본점|본사",window,maxsplit=1)[0]
                actual_site_provinces.update(_province_names(window))
                if len(actual_site_provinces)>=2:return True
                if _ACTUAL_CROSSING.search(window) and re.search(r"인접|시[·ㆍ]?도|광역|지역",window):return True
        if re.search(r"인접.{0,30}(?:시[·ㆍ]?도|지역).{0,80}(?:소재|위치|있는).{0,40}(?:시설|청사).{0,40}(?:유지|보수|관리)",compact):return True
    return False


def _multiple_province_clause(clause):
    regions=clause["regions"]
    provinces={r["province"] for r in regions if r.get("province")}
    if len(provinces)<2:return False
    # Multiple place names without a connective may describe relocation or a
    # parent territory; leave those semantics to the model.
    for left,right in zip(regions,regions[1:]):
        if left.get("province")==right.get("province"):continue
        between=clause["text"][left["end"]-clause["start"]:right["start"]-clause["start"]]
        if _JOIN.search(between):return True
    return False


def _valid_evidence(rec,doc_id,evidence):
    return bool(evidence) and len(evidence)<=500 and not evidence.startswith(("=","+","@")) and any(
        d.get("doc_id")==doc_id and evidence in d["text"] for d in _texts(rec))


def _joint_evidence(rec,region,performance):
    if region["doc_id"]==performance["doc_id"]:
        for doc in _texts(rec):
            if doc.get("doc_id")!=region["doc_id"]:continue
            position=doc["text"].find(performance["evidence"])
            if position<0:continue
            start=min(region["start"],position)
            end=max(region["end"],position+len(performance["evidence"]))
            if end-start<=500:return doc["doc_id"],doc["text"][start:end].strip()
    return performance["doc_id"],performance["evidence"]


def _performance_evidence(rec):
    """Reuse the strict performance parser after recognizing equivalent titles.

    Only eligibility heading spelling changes in a temporary record. Every
    returned evidence quote must still occur literally in an original document.
    """
    found=qualification_evidence(rec)
    if not any(_ALTERNATE_QUALIFICATION_TITLE.search(d["text"]) for d in _texts(rec)):
        return found
    view=deepcopy(rec)
    for doc in _texts(view):
        doc["text"]=_ALTERNATE_QUALIFICATION_TITLE.sub("입찰 참가자격",doc["text"])
    seen={(f["doc_id"],f["evidence"]) for f in found}
    for hit in qualification_evidence(view):
        key=(hit["doc_id"],hit["evidence"])
        if key not in seen and _valid_evidence(rec,*key):
            found.append(hit);seen.add(key)
    return found


def regional_overrides(rec):
    """Return certain positive corrections; an empty list is abstention."""
    contract=_contract_facts(rec)
    if not contract["reliable"] or contract["local_small_quote"] or contract["national_quote"]:return []
    if _explicit_quotation(rec):return []
    if contract["method"] not in {"일반경쟁","제한경쟁"}:return []
    qualifications=[c for c in extract_region_qualifications(rec)
                    if not _OPEN_REGION.search(_compact(c["text"]))
                    and _valid_evidence(rec,c["doc_id"],c["text"])]
    clauses=[c for c in qualifications if c["office_location_explicit"]]
    # The extractor admits terse "X 지역 업체" only under an explicit
    # qualification heading. Do not extend that inference to v5/v7/v8.
    basic_candidates=[c for c in qualifications if c["office_location_explicit"]
                      or (_TERSE_BASIC_QUALIFICATION.search(c["text"])
                          and not _TERSE_NONMANDATORY.search(c["text"]))]
    if not clauses and not basic_candidates:return []
    values=_amounts(rec)
    exceptions=_explicit_region_exception(rec)
    technical=any(_TECHNICAL.search(d["text"]) for d in _texts(rec))
    out=[]
    def emit(item,clause,rule,evidence=None,doc_id=None):
        ev=clause["text"] if evidence is None else evidence
        doc=clause["doc_id"] if doc_id is None else doc_id
        if _valid_evidence(rec,doc,ev):
            out.append({"item":item,"value":1,"evidence":ev,"doc_id":doc,
                        "rule":rule,"provenance":PROVENANCE[item]})
    threshold=NATIONAL_LIMIT if contract["law"]=="국가계약법" else LOCAL_SAFE_LIMIT
    if clauses and values and all(p>=threshold for p in values):
        emit("v5",clauses[0],"ordinary competitive goods/services: every reconciled estimate is at least the conservative regional ceiling")
    # Below 230M is a common conservative subrange. Technical local services
    # may have a lower ceiling, so those unresolved subtypes abstain here.
    below_common=(bool(values) and all(p<NATIONAL_LIMIT for p in values)
                  and not (contract["law"]=="지방계약법" and technical))
    if below_common and not exceptions:
        basic=next((c for c in basic_candidates if c["regions"] and all(r["unit"]=="basic" for r in c["regions"])),None)
        if basic:emit("v6",basic,"ordinary competitive tender restricts bidder office to basic municipalities below 230M")
        multiple=next((c for c in clauses if _multiple_province_clause(c)),None)
        if multiple:emit("v7",multiple,"multiple eligible provinces without an explicit supplied regional-expansion exception")
    performance=_performance_evidence(rec)
    alternative_conditions=any(_ALTERNATIVE_CONDITIONS.search(_compact(d["text"])) for d in _texts(rec))
    if clauses and performance and not alternative_conditions:
        doc,ev=_joint_evidence(rec,clauses[0],performance[0])
        emit("v8",clauses[0],"office region and quantitative past performance are both mandatory bidder qualifications",ev,doc)
    return out


def apply_regional_rules(rec,row):
    """Pure row adapter for optional integration after a normal model response."""
    corrected=deepcopy(row)
    for correction in regional_overrides(rec):
        item=correction["item"]
        corrected[item]=1
        corrected["e"+item[1:]]=correction["evidence"]
    return corrected
