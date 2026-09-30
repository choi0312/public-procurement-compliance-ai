"""Conservative, same-notice procedural corrections for v19 and v22.

Source-only timing and participation conditions. No IDs, labels, external
corpus, learned parameters, date inference, or cross-notice state are used.
An empty result is abstention, not a prediction that the notice is compliant.
"""
from __future__ import annotations

from copy import deepcopy
import re

from pps_rules import _qualification_sections


PROVENANCE = {
    "v19": ["항목표.json#항목.v19", "법령/(계약예규) 정부 입찰·계약 집행기준.txt#제5조의3제3항",
            "법령/지방자치단체 입찰 및 계약 집행기준.txt#제1장제1절7·제4장"],
    "v22": ["항목표.json#항목.v22", "법령/국가를 당사자로 하는 계약에 관한 법률 시행령.txt#제43조제6항 삭제",
            "법령/지방자치단체를 당사자로 하는 계약에 관한 법률 시행령.txt#제43조제7항 삭제"],
}
_CERTIFICATE = re.compile(r"(?:물품공급|제품공급|정품공급|공급|기술지원|A[/／]?S)[가-힣A-Za-z/／·ㆍ,()\-]{0,35}?확약서", re.I)
_UNRELATED_CERTIFICATE = re.compile(r"입찰보증|계약보증|납부이행|근로조건|임차용역|안전보건|청렴")
_EARLY = re.compile(r"(?:전자)?입찰(?:서)?(?:제출)?(?:마감(?:일|시각|시)?(?:전일|전|이전)?|전일?|참가(?:시|전)|등록(?:시|전)|시)(?:까지|에)?|제안서(?:제출|접수)(?:마감|시|전)|낙찰(?:통보|결정)이전")
_ACTION = re.compile(r"보유|소지|제출|발급|확보|구비")
_REQUIRED = re.compile(r"하여야|해야|필수|반드시|미제출.{0,30}(?:제외|불가)|보유한(?:자|업체)|소지한(?:자|업체)")
_LATE = re.compile(r"낙찰(?:자)?(?:결정|선정|통보)?(?:이후|후)|계약(?:체결)?(?:시에|시|이후|후)")
_EXPLICIT_NO_CERT = re.compile(r"(?:제출|보유|소지|발급).{0,18}(?:요구하지|의무(?:가)?없|필요(?:가)?없|받지않|하지않아도)|제출하지않아도.{0,25}(?:참가|입찰).{0,12}(?:가능|허용)")
_NONMANDATORY = re.compile(r"(?:보유|제출|발급).{0,12}(?:요구해서는안|요구하지않|의무(?:가)?없|필요(?:가)?없|하지않아도)|선택사항|선택제출")
_SELF_WRITTEN = re.compile(r"자체작성|(?:입찰자|제안사|당사)(?:가|에서)?(?:직접)?작성")
_BRIEFING = re.compile(r"(?:현장|사업|과업|입찰|제안요청서?)설명회|(?<![가-힣])설명회")
_PRESENTATION = re.compile(r"제안서?설명회|제안서?발표|평가위원|발표평가|프레젠테이션")
_OPTIONAL = re.compile(r"자율참석|참석은자율|참석여부.{0,15}관계없|참석하지않아도|불참(?:하여도|해도)|미참석.{0,20}불이익없|참석의무없|참석은선택")
_NO_EVENT = re.compile(r"설명회.{0,35}(?:개최하지않|실시하지않|생략|실시안함|개최안함)|설명회는.{0,30}(?:문서|규격서|과업지시서|제안요청서).{0,10}(?:갈음|대체)")
_NEG_ATTENDANCE = re.compile(r"미참석|불참|참석하지(?:아니한|않은|못한)")
_ENTRY_BAR = re.compile(r"입찰|참가|제안서|접수")
_BAR = re.compile(r"불가|제외|허용되지|허용하지|접수하지|거부|자격없")
_ATTEND_ONLY = re.compile(r"참석(?:한)?(?:업체|자)(?:에)?(?:한하여|한한|한정|만)|참석해야만")
_ATTEND_QUALIFICATION = re.compile(r"설명회.{0,70}참석한(?:자|업체)(?:[.(（]|이어야|여야|$)|설명회.{0,35}참석(?:은)?필수")
_BOUNDARY = re.compile(r"\n\s*(?:[가-하][.)]|\d{1,2}[.)]|[①-⑳○◦●□■▶※•❍‣]|[-*]\s|o\s)")


def _compact_map(text):
    positions = [i for i, ch in enumerate(text) if not ch.isspace()]
    return "".join(text[i] for i in positions), positions


def _source_clause(text, positions, start, end):
    begin, finish = positions[start], positions[end-1]+1
    left = text.rfind("\n", 0, begin)+1
    if begin-left > 180:
        left = begin
    right = min(len(text), left+500)
    split = text.find("\n\n", finish, right)
    if split >= 0:
        right = split
    bullet = _BOUNDARY.search(text, finish, right)
    if bullet:
        right = min(right, bullet.start())
    while left < right and (text[left].isspace() or text[left] in "=+@"):
        left += 1
    while right > left and text[right-1].isspace():
        right -= 1
    if finish > right:
        return None
    return {"start": left, "end": right, "text": text[left:right]}


def _documents(rec):
    return [d for d in rec.get("docs", []) if isinstance(d, dict) and isinstance(d.get("text"), str)]


def _correction(item, value, doc, clause, rule):
    return {"item": item, "value": int(value), "evidence": clause["text"] if value else "",
            "doc_id": str(doc.get("doc_id", "")), "start": clause["start"], "end": clause["end"],
            "source_evidence": clause["text"], "rule": rule, "provenance": PROVENANCE[item]}


def supply_timing_override(rec):
    """v19: explicit pre-bid issuance/possession beats later physical delivery.

    A certificate merely appearing in an un-timed list is deliberately not
    enough for either decision. Negative corrections require all observed
    matching certificate clauses to give an explicit later/exempt condition.
    """
    negative, undecided, seen = [], False, set()
    for doc in _documents(rec):
        compact, positions = _compact_map(doc["text"])
        for match in _CERTIFICATE.finditer(compact):
            if _UNRELATED_CERTIFICATE.search(match.group()):
                continue
            clause = _source_clause(doc["text"], positions, match.start(), match.end())
            if not clause:
                undecided = True
                continue
            key = (doc.get("doc_id"), clause["start"], clause["end"])
            if key in seen:
                continue
            seen.add(key)
            body = re.sub(r"\s+", "", clause["text"])
            if _SELF_WRITTEN.search(body):
                # An explicitly self-written service promise is not a proven
                # manufacturer/supplier-issued certificate requirement.
                undecided = True
                continue
            local_certificate = _CERTIFICATE.search(body)
            unrelated = _UNRELATED_CERTIFICATE.search(body, local_certificate.end()) if local_certificate else None
            if unrelated:
                body = body[:unrelated.start()]
            no_obligation = _EXPLICIT_NO_CERT.search(body) or _NONMANDATORY.search(body)
            # A waived physical submission does not waive explicit pre-bid
            # possession. Keep that obligation separate from submission timing.
            required_possession = re.search(r"(?:"+_EARLY.pattern+r")[^.]{0,100}(?:보유|소지|발급|확보|구비)(?:하여야|해야)", body)
            exempt_possession = re.search(r"(?:보유|소지|발급|확보|구비).{0,12}(?:요구하지|의무(?:가)?없|필요(?:가)?없|하지않아도)", body)
            if _EARLY.search(body) and _ACTION.search(body) and _REQUIRED.search(body) and (not no_obligation or required_possession and not exempt_possession):
                return _correction("v19", 1, doc, clause, "explicit supply/technical-support certificate required before bid completion")
            if no_obligation:
                negative.append(_correction("v19", 0, doc, clause, "explicit certificate requirement exemption"))
            elif _LATE.search(body) and _ACTION.search(body) and _REQUIRED.search(body) and not _EARLY.search(body):
                negative.append(_correction("v19", 0, doc, clause, "certificate required only at explicit post-award/contract stage"))
            else:
                undecided = True
    return negative[0] if negative and not undecided else None


def _negotiated_status(rec):
    meta = rec.get("meta") or {}
    if meta.get("적용계약법") not in ("국가계약법", "지방계약법"):
        return None
    award = re.sub(r"\s+", "", str(meta.get("낙찰방법", "")))
    notice_documents = [d["text"] for d in _documents(rec) if d.get("type") == "공고문"]
    notices = [re.sub(r"\s+", "", text) for text in notice_documents]
    explicit = []
    for text in notice_documents:
        for line in text[:3000].splitlines():
            body = re.sub(r"\s+", "", line)
            for match in re.finditer(r"(?:낙찰|계약)방법[:：](.{0,80})", body):
                if re.search(r"협상(?:에의한)?계약", match.group(1)):
                    explicit.append(True)
                if re.match(r"(?:최저가|적격심사|규격가격동시)", match.group(1)):
                    explicit.append(False)
    if explicit:
        return explicit[0] if len(set(explicit)) == 1 else None
    if "협상" in award:
        return True
    if award in ("적격심사제", "최저가낙찰제", "규격가격동시입찰", "소액수의견적") and not any("협상" in t for t in notices):
        return False
    return None


def briefing_override(rec):
    """v22: required pre-bid agency briefing attendance in negotiated tender."""
    status = _negotiated_status(rec)
    if status is None:
        return None
    negative, unresolved, seen = [], False, set()
    for doc in _documents(rec):
        compact, positions = _compact_map(doc["text"])
        qualification_sections = _qualification_sections(doc["text"])
        for match in _BRIEFING.finditer(compact):
            # Proposal presentations/evaluation and project-delivery briefings
            # have different purposes from an agency's pre-bid explanation.
            prefix = compact[max(0, match.start()-12):match.end()]
            if _PRESENTATION.search(prefix):
                continue
            clause = _source_clause(doc["text"], positions, match.start(), match.end())
            if not clause:
                unresolved = True
                continue
            key = (doc.get("doc_id"), clause["start"], clause["end"])
            if key in seen:
                continue
            seen.add(key)
            body = re.sub(r"\s+", "", clause["text"])
            optional = _OPTIONAL.search(body) or _NO_EVENT.search(body)
            in_qualification = any(a <= positions[match.start()] < b for a, b in qualification_sections)
            mandatory = ((_NEG_ATTENDANCE.search(body) and _ENTRY_BAR.search(body) and _BAR.search(body))
                         or (_ATTEND_ONLY.search(body) and _ENTRY_BAR.search(body))
                         or (in_qualification and _ATTEND_QUALIFICATION.search(body)))
            if mandatory and optional and status:
                unresolved = True  # Conflicting requirements, or different events in one clause.
                continue
            if mandatory and not optional and status:
                return _correction("v22", 1, doc, clause, "agency briefing attendance is mandatory for bid/proposal eligibility in negotiated tender")
            if optional or status is False:
                negative.append(_correction("v22", 0, doc, clause,
                                             "non-negotiated tender" if status is False else "explicitly optional or omitted pre-bid briefing"))
            else:
                unresolved = True
    return negative[0] if negative and not unresolved else None


def procedure_overrides(rec):
    return [correction for correction in (supply_timing_override(rec), briefing_override(rec)) if correction is not None]


def apply_procedure_rules(rec, row):
    out = deepcopy(row)
    for correction in procedure_overrides(rec):
        out[correction["item"]] = correction["value"]
        out["e"+correction["item"][1:]] = correction["evidence"]
    return out
