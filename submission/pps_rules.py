"""Narrow, provided-source statutory corrections after the required LLM call.

This module reads one notice only. It contains no IDs, labels, learned state,
external data, or inference-time API calls. An abstention is NOT a zero label.
v2 compares the CURRENT estimated price with the supplied KRW 230M threshold;
the amount of PAST required performance is not compared with current price.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


V2_THRESHOLD = Decimal("230000000")
V2_PROVENANCE = [
    "법령패키지/법령/(계약예규) 정부 입찰·계약 집행기준.txt 제5조제1항 단서",
    "법령패키지/법령/국가를 당사자로 하는 계약에 관한 법률 시행규칙.txt 제25조",
    "법령패키지/법령/지방자치단체를 당사자로 하는 계약에 관한 법률 시행령.txt 제20조제1항",
    "법령패키지/법령/국가를 당사자로 하는 계약에 관한 법률 등의 재정경제부장관이 정하는 고시금액.txt 제1항가목",
    "https://dacon.io/competitions/official/236754/talkboard/417262",
]

_QUAL_TITLE = re.compile(
    r"^(?:[\dⅠⅡⅢⅣⅤⅥ가-하]+[.．)\-]\s*|[□■◈○◦●]\s*)?"
    r"(?:(?:입찰|견적(?:제출)?|제안(?:서제출)?|응모|신청))?참가자격"
    r"(?=$|[:：※(（\[【]|및|조건|요건)"
)
_OTHER_TITLE = re.compile(
    r"^(?:\d{1,2}[.．]|[ⅠⅡⅢⅣⅤⅥ]+[.．)]|[□■◈])"
    r"(?:제안서|가격입찰|입찰서|견적서|낙찰|제출서류|제출방법|입찰보증|입찰의무효|입찰무효|"
    r"평가|심사|과업|계약|접수|유의|기타|입찰추진|입찰일정|청렴)"
)
_ENTRY = re.compile(r"^\s*(?:[가-하][.．)]|\d{1,2}[.)]|[①-⑳○◦●□■▶※]|[-•*])\s*")
_HISTORY = re.compile(r"실\s*적")
_AMOUNT_MIN = re.compile(
    r"\d[\d,.\s]*(?:억\s*|천\s*만\s*|백\s*만\s*|만\s*|천\s*)?"
    r"(?:원|건|회|대|명|개|톤|㎡|m2)\s*(?:\([^\n)]{0,30}\)\s*)?이\s*상"
)
_REQUIRED = re.compile(
    r"실\s*적.{0,140}?(?:있\s*는\s*(?:자|업체|기업)|있\s*어야|"
    r"보\s*유\s*(?:한|하\s*여야|해야|업체|기업)|이\s*상\s*인\s*(?:자|업체|기업)|"
    r"(?:업체|기업)\s*만.{0,20}참가)", re.S
)
_NOT_QUAL = re.compile(
    r"평가|배점|가점|득점|\d\s*점|실적\s*(?:증명서|증명원|총괄표|집계표)|"
    r"(?:실적|경험).{0,25}(?:없어도|없더라도|무관|해당\s*없음|요구하지)|"
    r"(?:하도급\s*수행자|하수급인|참여\s*연구원|책임\s*연구원|투입\s*인력)"
)
_ALTERNATIVE = re.compile(r"다음.{0,25}(?:어느\s*하나|하나\s*이상)|실적.{0,60}(?:또는|이거나)")
_PRICE_LABEL = re.compile(
    r"추\s*정\s*가\s*격(?:\s*\([^\n)]{0,25}\))?\s*[:：]\s*(?:금\s*)?"
)
_BODY_MONEY = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>억|천\s*만|백\s*만|만|천|백)?\s*원"
)


def _compact(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _meta_price(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    raw = str(value).strip()
    if raw.endswith("원"):
        raw = raw[:-1].strip()
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        return None
    try:
        number = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def _documents(rec: dict) -> list[dict]:
    return [d for d in rec.get("docs", []) if isinstance(d, dict) and isinstance(d.get("text"), str)]


def effective_price(rec: dict) -> dict:
    """Expose conservative price facts; never convert a VAT-included budget.

    Explicit colon-labelled current estimates are reconciled with public meta.
    Quoted legal bands ('추정가격 1억원 미만') and table column headers are not
    current estimates. Unsupported/ambiguous direct values cause abstention.
    Differences within the SAME statutory band are retained as a warning but
    cannot change this single threshold test. Across-band differences abstain.
    """
    meta = rec.get("meta", {}) or {}
    p = _meta_price(meta.get("입찰추정가격"))
    body = []
    unsupported = False
    units = {"": 1, "백": 100, "천": 1000, "만": 10000,
             "백만": 1000000, "천만": 10000000, "억": 100000000}
    for doc in _documents(rec):
        # Primary notice fields determine the contract estimate; an attachment
        # can include unrelated sample prices and prior-contract forms.
        if doc.get("type") != "공고문":
            continue
        t = doc["text"]
        for m in _PRICE_LABEL.finditer(t):
            prior = t[max(t.rfind("\n", 0, m.start()) + 1, m.start() - 80):m.start()]
            if re.search(r"평가|배점|예시|산식|기준금액|고시금액|대상업체|실적", prior):
                continue
            tail = t[m.end():m.end() + 100]
            money = _BODY_MONEY.match(tail)
            if not money:
                unsupported = True
                continue
            value = Decimal(money["num"].replace(",", "")) * units[_compact(money["unit"])]
            following = tail[money.end():money.end() + 20]
            if value <= 0 or re.match(r"\s*(?:미만|이상|이하|초과|~|∼|부터)", following):
                unsupported = True
                continue
            if re.search(r"(?:부가(?:가치)?세|VAT)\s*(?:포함|포함된)", following, re.I):
                unsupported = True  # Do not guess whether label or VAT text is wrong.
                continue
            body.append({"amount": str(value), "doc_id": doc.get("doc_id", ""),
                         "evidence": t[m.start():m.end() + money.end()]})
    values = ([p] if p is not None else []) + [Decimal(x["amount"]) for x in body]
    bands = {v < V2_THRESHOLD for v in values}
    reliable = bool(values) and len(bands) == 1 and not unsupported
    return {"reliable": reliable,
            "below_threshold": next(iter(bands)) if reliable else None,
            "meta_amount": str(p) if p is not None else None,
            "body_estimates": body,
            "same_band_amount_disagreement": len(set(values)) > 1,
            "reason": "직접 추정가격의 구간 일치" if reliable else
                      "유효한 추정가격 부재 또는 직접 본문 금액·단위·VAT·구간 불확실"}


def _qualification_sections(text: str) -> list[tuple[int, int]]:
    lines = list(re.finditer(r"[^\n]+", text))
    result = []
    for i, line in enumerate(lines):
        if not _QUAL_TITLE.search(_compact(line.group())):
            continue
        start = line.end()
        end = min(len(text), start + 6500)
        for following in lines[i + 1:]:
            if following.start() >= end:
                break
            if _OTHER_TITLE.search(_compact(following.group())):
                end = following.start()
                break
        result.append((start, end))
    return result


def qualification_evidence(rec: dict) -> list[dict]:
    """Retrieve literal mandatory quantitative past-performance clauses only.

    Precision is preferred: a generic '신용과 실적이 있는 자', staff CVs,
    required proof forms alone, score tables, and ambiguous OR alternatives
    cannot trigger this postprocessor. A missed clause remains with the LLM.
    """
    hits = []
    seen = set()
    for doc in _documents(rec):
        text = doc["text"]
        for begin, end in _qualification_sections(text):
            section = text[begin:end]
            # An alternative-eligibility heading needs semantic resolution.
            if _ALTERNATIVE.search(section[:300]):
                continue
            lines = list(re.finditer(r"[^\n]+", section))
            for i, line in enumerate(lines):
                # Short wrapped clauses are joined only until the next listed
                # condition, preserving the exact original newlines/spaces.
                stop = line.end()
                if not (_HISTORY.search(line.group()) and _AMOUNT_MIN.search(line.group())
                        and _REQUIRED.search(line.group())):
                    for following in lines[i + 1:i + 4]:
                        if _ENTRY.match(following.group()) or following.end() - line.start() > 500:
                            break
                        stop = following.end()
                raw = section[line.start():stop].strip()
                if not (_HISTORY.search(raw) and _AMOUNT_MIN.search(raw) and _REQUIRED.search(raw)):
                    continue
                if _NOT_QUAL.search(raw) or _ALTERNATIVE.search(raw):
                    continue
                if len(raw) > 500:
                    continue
                key = (doc.get("doc_id", ""), raw)
                if key in seen:
                    continue
                seen.add(key)
                hits.append({"doc_id": doc.get("doc_id", ""), "evidence": raw})
    return hits


def _contract_facts(rec: dict) -> dict:
    meta = rec.get("meta", {}) or {}
    law = _compact(meta.get("적용계약법"))
    scope = _compact(meta.get("업무구분"))
    method = _compact(meta.get("계약방법"))
    award = _compact(meta.get("낙찰방법"))
    intros = [_compact(d["text"][:3000]) for d in _documents(rec) if d.get("type") == "공고문"]
    body_quote = any(re.search(r"(?:소액)?수의(?:계약)?[^。]{0,30}견적(?:서)?(?:제출)?[^。]{0,15}(?:안내|공고)", t[:1200]) for t in intros)
    meta_quote = method == "수의계약" and award == "소액수의견적"
    # Opposite statutory references in other procedural boilerplate are common;
    # flag only an explicit statement naming the law APPLIED to this contract.
    opposite = "국가" if law == "지방계약법" else "지방"
    law_conflict = any(re.search(r"(?:본|이)(?:입찰|계약|용역).{0,35}" + opposite + r"계약법.{0,20}적용", t)
                       for t in intros)
    reliable = (law in {"국가계약법", "지방계약법"}
                and ("물품" in scope or "용역" in scope) and "공사" not in scope
                and not law_conflict)
    body_construction = any(re.search(r"공사명[:：]|(?:시설)?공사(?:전자입찰)?공고", t[:500]) for t in intros)
    if "공사" in scope or body_construction or not intros:
        reliable = False
    if body_quote != meta_quote:
        # Do not turn missing or conflicting procurement-method evidence into
        # an exception, or blindly treat it as ordinary competitive tendering.
        reliable = False
    if not meta_quote and not (method in {"일반경쟁", "제한경쟁", "지명경쟁"} and "수의" not in award):
        reliable = False
    return {"reliable": reliable, "law": law, "scope": scope,
            "method": method, "award": award, "body_quote": body_quote,
            "local_small_quote": law == "지방계약법" and meta_quote and body_quote,
            "national_quote": law == "국가계약법" and meta_quote and body_quote}


def v2_override(rec: dict) -> dict | None:
    """Return a confident v2/e2 correction, or None (leave model unchanged).

    The supplied v2 criterion requires current price below KRW230M. A reliable
    price at/above that boundary disproves v2, without deciding v3 or v4.
    No conclusion follows from a regex failing to find a clause.
    National negotiated quotations are left for the model: absence of the local
    exception alone does not establish the ordinary competitive-contract rule.
    """
    contract = _contract_facts(rec)
    if not contract["reliable"] or contract["national_quote"]:
        return None
    price = effective_price(rec)
    if not price["reliable"]:
        return None
    if not price["below_threshold"]:
        return {"v2":0,"e2":"","reason":"신뢰 가능한 이번 추정가격이 230,000,000원 이상으로 v2 금액 적용범위 밖; 과다 실적·실적 범위 제한은 별도 항목",
                "provenance":list(V2_PROVENANCE),"facts":{"contract":contract,"price":price}}
    clauses = qualification_evidence(rec)
    if not clauses:
        return None
    violation = 0 if contract["local_small_quote"] else 1
    return {"v2": violation, "e2": clauses[0]["evidence"] if violation else "",
            "reason": "지방계약의 실제 소액수의 견적 허용예외" if not violation else
                      "이번 추정가격이 230,000,000원 미만이고 정량적 과거실적이 필수 참가자격임. 요구실적/추정가격 비율은 v2의 예외가 아님.",
            "provenance": list(V2_PROVENANCE),
            "facts": {"contract": contract, "price": price, "clause": clauses[0]}}


def apply_statutory_rules(rec: dict, row: dict) -> dict:
    """Apply to a resolved flat CSV row; never mutate input or other labels."""
    result = dict(row)
    correction = v2_override(rec)
    if correction is not None:
        if isinstance(result.get("v2"), dict):
            raise ValueError("Apply statutory rules to the resolved flat CSV row, not raw model JSON")
        result.update(v2=correction["v2"], e2=correction["e2"])
    return result


def v21_override(rec: dict) -> dict | None:
    """Optional explicit joint-share rule; NOT enabled by apply_statutory_rules.

    National ordinary joint performance has a 10% default with a 20% adjustment
    provision, so this narrow rule flags only <8%. The local 5% default's 4~6%
    adjustment is explicitly for construction; ordinary services below 5% are
    eligible here. Split performance, mixed modes, unknown mode, contradictory
    joint participation, construction and individual representative shares abstain.
    """
    meta = rec.get("meta", {}) or {}
    law = _compact(meta.get("적용계약법"))
    scope = _compact(meta.get("업무구분"))
    mode = _compact(meta.get("공동도급구성방식"))
    if law not in {"국가계약법", "지방계약법"} or not ("물품" in scope or "용역" in scope) or "공사" in scope:
        return None
    if mode and mode != "공동이행":
        return None
    notices = [d for d in _documents(rec) if d.get("type") == "공고문"]
    if not notices:
        return None
    body = "\n".join(d["text"] for d in notices)
    compact = _compact(body)
    if re.search(r"공사명[:：]|(?:시설)?공사(?:전자입찰)?공고", compact[:500]):
        return None
    if re.search(r"공동(?:도급|수급|이행|계약)(?:은|는|을|이|에의한[^.]{0,15})?.{0,15}(?:불가|불허|금지|허용(?:하지|되지)않)", compact):
        return None
    if re.search(r"(?:분담이행|주계약자관리|혼합방식|서로다른법령)", compact):
        return None
    if mode != "공동이행" and not re.search(r"공동이행(?:방식)?(?:으로|을|만|에의한|[)）]).{0,35}(?:허용|가능|참여|구성)", compact):
        return None
    # Positive-eligibility context is still required even when meta names mode.
    if not re.search(r"공동(?:이행|도급|수급|계약).{0,60}(?:허용|가능|구성하여|구성하며|구성해야|구성하여야)", compact):
        return None
    rate_pattern = re.compile(
        r"최\s*소\s*(?:지\s*분\s*율|출\s*자\s*비\s*율|참\s*여\s*비\s*율)\s*"
        r"(?:은|는|을|:|：)?\s*(?P<rate>\d+(?:\.\d+)?)\s*(?:%|퍼센트)\s*이\s*상"
    )
    clauses = []
    for doc in notices:
        text = doc["text"]
        for match in rate_pattern.finditer(text):
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            if end < 0:
                end = len(text)
            raw = text[start:end].strip()
            prior = text[max(start, match.start() - 30):match.start()]
            context = text[max(0, start - 500):min(len(text), end + 150)]
            if len(raw) > 500 or re.search(r"평가|배점|예시|서식|지역업체|대표(?:사|자)", prior):
                continue
            if not re.search(r"공동\s*(?:수급|도급|계약|이행)|구성원|업체별", context):
                continue
            rate = Decimal(match["rate"])
            if rate < 0 or rate > 100:
                continue
            clauses.append({"rate": str(rate), "doc_id": doc.get("doc_id", ""), "evidence": raw})
    if not clauses or len({c["rate"] for c in clauses}) != 1:
        return None
    rate = Decimal(clauses[0]["rate"])
    safe_floor = Decimal("8") if law == "국가계약법" else Decimal("5")
    if rate >= safe_floor:
        return None
    return {"v21": 1, "e21": clauses[0]["evidence"],
            "reason": f"일반 물품·용역 공동이행의 명시적 구성원 최소지분율 {rate}%가 안전한 하한 {safe_floor}%보다 작음",
            "facts": {"law": law, "scope": scope, "mode": mode or "본문 공동이행 명시", **clauses[0]},
            "provenance": ["법령패키지/법령/(계약예규) 공동계약운용요령.txt 제9조제5항",
                           "법령패키지/법령/지방자치단체 입찰 및 계약 집행기준.txt 제6장 제2절 1-나"]}
