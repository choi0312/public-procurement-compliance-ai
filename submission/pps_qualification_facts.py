"""Literal, record-local qualification facts; no labels or product classification.

Only actual participant-qualification sections of the primary notice can supply
positive facts. Absence additionally needs an observed, untruncated notice and
closed sections, without unresolved cross-references or alternative eligibility.
The helper is deliberately incomplete. Unknown leaves semantic LLM facts intact.
"""
from __future__ import annotations

import re

from pps_rules import _qualification_sections


_END = re.compile(r"^\s*\d{1,2}(?:-\d+)?[.．]\s*(?:공동|제출|접수|입찰보증|낙찰|협상|제안서|제안\s*공모|가격|구매입찰|입찰서|입찰의|입찰무효|계약|청렴|기타|유의|평가|심사)")
_ENTRY = re.compile(r"^\s*(?:[가-하][.．)]|\d{1,2}[.)]|[①-⑳○◦●□■▶※]|[ㅇ•*])\s*")
_CERT = re.compile(r"직접생산(?:확인)?(?:증명서|확인서)")
_SCOPE = re.compile(r"중[·ㆍ․∙,・‧･/]?소기업|중기업|소기업|소상공인")
_POSSESS = re.compile(r"(?:소지|보유)(?:한|하(?:여야|고|는|며|였)|해야|업체|자)|발급받(?:은|아야)|갖추(?:어야|고있는|고있어야)|(?:자격|요건)을갖춘|해당하는(?:업체|자)|(?:업체|기업|자)(?:이어야|여야)|(?:으로|로)제한(?:합니다|하며|한다)")
_LEGAL_NAMES = re.compile(r"[「｢][^」｣]{0,160}[」｣]|‘[^’]{0,160}’|“[^”]{0,160}”|'[^']{0,160}'|\"[^\"]{0,160}\"|중소기업기본법|중소기업제품구매촉진및판로지원에관한법률(?:시행령)?|중소기업범위및확인에관한규정|중소기업자와의우선조달계약(?:에대한예외)?")
_FIRM_CERT = re.compile(r"(?:중[·ㆍ․∙,・‧･/]?소기업|중기업|소기업|소상공인)(?:(?:[·ㆍ․∙,・‧･/]|또는|및)?(?:소기업|소상공인|중기업))*[’'”\"〉>＞]?(?:확인서|확인증명서)")
_ALT = re.compile(r"(?:다음|아래).{0,35}(?:어느하나|하나이상)|(?:자격|조건).{0,30}(?:중하나|택일)")
_EXTERNAL = re.compile(r"(?:자격|요건|조건).{0,80}(?:제안요청서|과업지시서|규격서|별첨|붙임).{0,30}(?:참고|참조|따|기재|확인)|(?:제안요청서|과업지시서|규격서|별첨|붙임).{0,45}(?:자격|요건|조건)")
_NOISE = re.compile(r"^\s*(?:※|\*|[-•])|(?:제출서류|서류목록|각?\s*1\s*부|증빙서류)|(?:공공구매|공공정보|공공구매정보|종합정보)망|면세|이윤")
_NEGATIVE = re.compile(r"(?:확인서|증명서|기업|소상공인).{0,35}(?:없어도|없이|무관하게|관계없이|요구하지|불필요)")


def _norm_map(text: str) -> tuple[str, list[int]]:
    chars, offsets = [], []
    for i, char in enumerate(text):
        if not char.isspace():
            chars.append(char)
            offsets.append(i)
    return "".join(chars), offsets


def _mask_laws(text: str) -> str:
    # Keep positions intact for literal evidence. The statute title is not an
    # actor: '중소기업기본법 제2조제2항에 따른 소기업' means small_only.
    def mask(match):
        value = match.group()
        return "#" * len(value) if re.search(r"법|규정|요령|시행령|시행규칙|우선조달계약", value) else value
    return _LEGAL_NAMES.sub(mask, text)


def _sections(text: str) -> list[dict]:
    result = []
    for start, inherited_end in _qualification_sections(text):
        # Reuse the established detector, then recognize a few ordinary next
        # section headings it intentionally did not need for the v2-only rule.
        end = inherited_end
        for m in re.finditer(r"[^\n]+", text[start:inherited_end]):
            if _END.match(m.group()):
                end = start + m.start()
                break
        if len(text[start:end].strip()) < 10:
            continue  # e.g. a table of contents heading with no actual terms
        following = text[end:text.find("\n", end) if "\n" in text[end:] else len(text)]
        # A limit cutoff/end-of-file is not proof the qualification is complete.
        closed = end < len(text) and end - start < 6500 and bool(re.match(r"\s*(?:\d|[ⅠⅡⅢⅣⅤⅥ□■◈])", following))
        result.append({"start": start, "end": end, "closed": closed, "text": text[start:end]})
    return result


def _clauses(section: str) -> list[tuple[int, int]]:
    lines = list(re.finditer(r"[^\n]+", section))
    if not lines:
        return []
    starts = [lines[0].start()]
    for line in lines[1:]:
        if _ENTRY.match(line.group()):
            starts.append(line.start())
    return [(start, starts[i + 1] if i + 1 < len(starts) else len(section)) for i, start in enumerate(starts)]


def _evidence(raw: str, offsets: list[int], start: int, end: int) -> str | None:
    if not offsets or end <= start:
        return None
    raw = raw.rstrip()
    # Match the semantic-facts schema's 350-character evidence field while
    # also remaining below the competition CSV's 500-character limit.
    if len(raw) <= 350:
        return raw.strip()
    a = max(0, offsets[start] - 50)
    b = min(len(raw), a + 350)
    if offsets[end - 1] >= b:
        return None
    return raw[a:b].strip()


def _clause_facts(raw: str) -> dict:
    norm, offsets = _norm_map(raw)
    masked = _mask_laws(norm)
    # A nonprofit's ADDITIONAL participation is independent of for-profit SME
    # scope. Its waiver text is ignored here, never converted to unrestricted.
    main = re.split(r"(?:또는)?(?:비영리법인|비영리단체)", masked, maxsplit=1)[0]
    negative = bool(_NEGATIVE.search(main))
    direct = []
    scopes = []
    for cert in _CERT.finditer(main):
        suffix = main[cert.end():cert.end() + 260]
        possess = _POSSESS.search(suffix)
        if not negative and possess:
            ev = _evidence(raw, offsets, cert.start(), cert.end() + possess.end())
            if ev:
                direct.append(ev)
    # Scope tokens must belong to a possession/actor qualification, not a
    # statute name, verification website, header, or list of required forms.
    possess = _POSSESS.search(main)
    scope_tokens = list(_SCOPE.finditer(main))
    if possess and scope_tokens and not negative:
        actor = [m for m in scope_tokens if not re.match(r"(?:제품|공공|범위|기본法|기본법)", main[m.end():])]
        actor = [m for m in actor if abs(m.start() - possess.start()) <= 350]
        if actor:
            certs = [m for m in _FIRM_CERT.finditer(main) if 0 <= possess.start() - m.end() <= 260]
            cert_values = {"sme" if m.group().startswith("중") else "small_only" for m in certs}
            if len(cert_values) > 1:
                return {"direct": direct, "scopes": [], "direct_unresolved": False,
                        "scope_unresolved": True, "negative": negative}
            # A broad SME description AND a mandatory small-business certificate
            # admits only small businesses. The required certificate supplies
            # the effective intersection, not a law/issuing-agency name.
            has_middle = any(m.group().startswith("중") for m in actor)
            kind = next(iter(cert_values)) if cert_values else ("sme" if has_middle else "small_only")
            ev = _evidence(raw, offsets, min(m.start() for m in actor), max(possess.end(), max(m.end() for m in actor)))
            if ev:
                scopes.append({"value": kind, "evidence": ev})
    direct_unresolved = bool(_CERT.search(main)) and not direct and (
        not _NOISE.search(raw) or bool(re.search(r"발급|유효기간|마감일", main)))
    scope_unresolved = bool(_SCOPE.search(main)) and not scopes and not _NOISE.search(raw)
    return {"direct": direct, "scopes": scopes, "direct_unresolved": direct_unresolved,
            "scope_unresolved": scope_unresolved, "negative": negative}


def extract_qualification_facts(rec: dict) -> dict:
    """Extract known facts and exact source; NEVER output final v/e labels."""
    result = {"direct_production_required": "unknown", "direct_production_e": None,
              "enterprise_scope": "unknown", "enterprise_e": None, "diagnostics": {}}
    docs = [d for d in rec.get("docs", []) if isinstance(d, dict) and isinstance(d.get("text"), str)]
    primary = [d for d in docs if d.get("type") == "공고문"]
    complete = rec.get("input_completeness", {}) or {}
    dropped = rec.get("dropped_doc_counts", {}) or {}
    observed = (complete.get("공고문_실재") is True and complete.get("추출_성공") is True
                and not any("공고문" in str(k) and int(v or 0) > 0 for k, v in dropped.items()))
    sections, direct, scopes = [], [], []
    blockers = []
    direct_unresolved = scope_unresolved = False
    for doc in primary:
        found = _sections(doc["text"])
        if not found:
            blockers.append("공고문의 참가자격 구간 미식별")
        for sec in found:
            sections.append({"doc_id": doc.get("doc_id", ""), **{k:sec[k] for k in ("start", "end", "closed")}})
            normalized, _ = _norm_map(sec["text"])
            if not sec["closed"]:
                blockers.append("자격 구간의 끝 미확인")
            if _ALT.search(normalized):
                blockers.append("자격 전체의 선택적 OR 조건")
            if _EXTERNAL.search(normalized):
                blockers.append("외부 문서 자격 참조")
            for a, b in _clauses(sec["text"]):
                cf = _clause_facts(sec["text"][a:b])
                direct.extend({"doc_id": doc.get("doc_id", ""), "text": t} for t in cf["direct"])
                scopes.extend({"doc_id": doc.get("doc_id", ""), **t} for t in cf["scopes"])
                direct_unresolved |= cf["direct_unresolved"]
                scope_unresolved |= cf["scope_unresolved"]
                if cf["negative"]:
                    blockers.append("자격증명 면제/부정 조건 미해결")
        # An affirmative qualification elsewhere in the same notice is not
        # promoted here; it blocks an overconfident ABSENCE result instead.
        outside = doc["text"]
        for sec in reversed(found):
            outside = outside[:sec["start"]] + " " * (sec["end"] - sec["start"]) + outside[sec["end"]:]
        for line in outside.splitlines():
            cf = _clause_facts(line)
            direct_unresolved |= bool(cf["direct"])
            scope_unresolved |= bool(cf["scopes"])
    # A provided attachment may spell out an actual qualification that was
    # omitted/misordered in the extracted notice (e.g. multi-column OCR). It
    # cannot supply affirmative primary-notice facts here, but prevents absence
    # claims and prevents overwriting contradictory firm-scope facts.
    secondary_direct = False
    secondary_scopes = set()
    for doc in docs:
        if doc.get("type") == "공고문":
            continue
        for sec in _sections(doc["text"]):
            for a, b in _clauses(sec["text"]):
                cf = _clause_facts(sec["text"][a:b])
                secondary_direct |= bool(cf["direct"])
                secondary_scopes.update(s["value"] for s in cf["scopes"])
    direct_unresolved |= secondary_direct and not direct
    scope_unresolved |= bool(secondary_scopes) and not scopes
    primary_scopes = {s["value"] for s in scopes}
    secondary_conflict = bool(primary_scopes and secondary_scopes and secondary_scopes != primary_scopes)
    if secondary_conflict:
        blockers.append("첨부 실제 자격과 기업범위 충돌")
    absence_ok = bool(primary and sections and observed and not blockers)
    # Global alternative/referral/negative clauses can change whether an
    # otherwise affirmative line is a mandatory condition, so abstain as well.
    mandatory_ok = bool(sections and not any("OR" in x or "외부" in x or "부정" in x for x in blockers))
    if direct and mandatory_ok:
        result["direct_production_required"] = "yes"
        result["direct_production_e"] = direct[0]["text"]
    elif absence_ok and not direct_unresolved:
        result["direct_production_required"] = "no"
    values = {s["value"] for s in scopes}
    if len(values) == 1 and mandatory_ok and not secondary_conflict:
        result["enterprise_scope"] = next(iter(values))
        result["enterprise_e"] = scopes[0]["evidence"]
    elif not values and absence_ok and not scope_unresolved:
        result["enterprise_scope"] = "unrestricted"
    elif len(values) > 1:
        blockers.append("기업범위 자격 문구의 충돌")
    result["diagnostics"] = {"primary_notice_observed": observed, "absence_eligible": absence_ok,
                             "sections": sections, "blockers": sorted(set(blockers)),
                             "direct_unresolved": direct_unresolved, "scope_unresolved": scope_unresolved,
                             "direct_candidates": direct, "scope_candidates": scopes}
    return result
