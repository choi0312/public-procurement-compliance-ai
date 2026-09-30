"""Narrow v20 source-presence checks for confirmed actual software work.

Provided SW participation directive Article3(2) allows the notice OR RFP to
state the basis. Missing RFPs therefore block a definitive absence override.
No IDs, labels, external documents or cross-notice state are accessed.
"""
from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal

from pps_product_facts import _actual_fields, _norm, _FIELD, _prices


PROVENANCE = ["항목표.json#항목.v20",
              "법령패키지/법령/소프트웨어 진흥법.txt#제2조제2~3호·제48조",
              "법령패키지/법령/중소 소프트웨어사업자의 사업 참여 지원에 관한 지침.txt#제2조·제3조제2항·별표1"]
_SOFTWARE_TASK = re.compile(r"(?:소프트웨어|정보시스템|전산시스템|경영정보시스템|학습분석시스템|홈페이지|누리집|웹사이트).{0,90}(?:설계|개발|구축|고도화|유지보수|유지관리|운영|개편)")
_HARDWARE = re.compile(r"(?:사무기기|전산기기|데스크톱|데스크탑|노트북|컴퓨터|장비).{0,30}(?:임차|렌탈|대여|구매|구입)")
_PARTICIPATION = re.compile(r"사업금액별참여제한|대기업참여제한하한(?:제도)?|사업금액의하한.{0,60}(?:적용|참여)|(?:20|40|80)억(?:원)?(?:미만|이상).{0,180}(?:중소소프트웨어사업자|대기업|중견기업).{0,80}(?:참여|참가)|(?:중소소프트웨어사업자|대기업|중견기업).{0,180}(?:20|40|80)억(?:원)?(?:미만|이상).{0,80}(?:참여|참가)")
_UNCERTAIN = re.compile(r"소프트웨어.{0,25}제(?:48조|24조의2)|중소소프트웨어사업자의사업참여지원에관한지침|대기업.{0,45}참여|사업금액.{0,45}하한|참여제한금액")
_SCOPE_MIX = re.compile(r"분담이행|소프트웨어사업과타사업|sw사업과타사업")


def _docs(rec):
    return [d for d in rec.get("docs", []) if isinstance(d, dict) and isinstance(d.get("text"), str)]


def software_scope(rec, product_fact=None):
    """Return known actual SW scope plus literal source, otherwise abstain."""
    fields = [f for f in _actual_fields(rec)
              if (m := _FIELD.search(f["text"])) is not None and m.start() <= 16]
    if any(_HARDWARE.search(_norm(f["text"])) for f in fields):
        return {"software": "unknown", "reason": "실제 사무/전산기기 임차는 부수적 SW만으로 SW사업 확정하지 않음"}
    all_text = _norm("\n".join(d["text"] for d in _docs(rec)))
    if _SCOPE_MIX.search(all_text):
        return {"software": "unknown", "reason": "SW와 다른 사업의 분담·혼합 범위 미확정"}
    for f in fields:
        if _SOFTWARE_TASK.search(_norm(f["text"])):
            return {"software": "yes", "reason": "실제 사업명/과업명에 SW 과업 명시", "evidence": f["text"][:350]}
    # A purchase-summary purpose field is actual work; its later unchecked
    # information-project examples and generic checklist are not.
    for d in _docs(rec):
        if d.get("type") not in ("제안요청서", "과업지시서", "규격서"):
            continue
        for m in re.finditer(r"용\s*도\s*개\s*요|사\s*용\s*목\s*적", d["text"]):
            part = d["text"][m.start():m.start()+250]
            part = re.split(r"신의성실|대금지불|지체상금|지식재산권", part)[0]
            if _SOFTWARE_TASK.search(_norm(part)):
                return {"software": "yes", "reason": "구매요약서 사용목적에 실제 SW 설계·개발 명시", "evidence": part.strip()[:350]}
    # License purchase is an economic SW activity under supplied Act2. A
    # bundled OEM OS in a hardware rental spec is not the main purchase.
    code_text = str((rec.get("meta") or {}).get("세부품명번호목록") or "")
    license_fields = [f for f in fields if re.search(r"라이선스.{0,40}(?:갱신|구매)|(?:운영체제|소프트웨어).{0,30}구매", _norm(f["text"]))]
    if license_fields and ("운영체제" in code_text or "소프트웨어" in code_text or re.search(r"(?:운영체제|소프트웨어)(?:의)?사용권|os버전업그레이드", all_text)):
        return {"software": "yes", "reason": "실제 운영체제/SW 라이선스 구매·갱신", "evidence": license_fields[0]["text"][:350]}
    if product_fact:
        for candidate in product_fact.get("candidates", []):
            if _norm(candidate.get("special_condition")) == "소프트웨어진흥법제48조적용":
                e = candidate.get("source", "")
                if e and any(e in d["text"] for d in _docs(rec)) and "실제" in candidate.get("match", ""):
                    return {"software": "yes", "reason": "실제 구매대상에 연결된 제공 SW 제품 후보", "evidence": e[:350]}
    return {"software": "unknown", "reason": "실제 SW 주과업 불확실; 1468/증명서/메타만으로 확정하지 않음"}


def software_participation_override(rec, product_fact=None):
    scope = software_scope(rec, product_fact)
    if scope["software"] != "yes":
        return None
    meta = rec.get("meta") or {}
    if meta.get("적용계약법") not in ("국가계약법", "지방계약법"):
        return None
    uncertain = False
    for d in _docs(rec):
        if d.get("type") not in ("공고문", "제안요청서", "과업지시서", "규격서"):
            continue
        text = d["text"]
        # Allow wrapped clauses, preserve the original substring, and do not
        # join an entire document's unrelated amount and participation words.
        lines = list(re.finditer(r"[^\n]+", text))
        for i, line in enumerate(lines):
            end = lines[min(i+2, len(lines)-1)].end()
            raw = text[line.start():min(end, line.start()+500)]
            compact = _norm(raw)
            if _PARTICIPATION.search(compact):
                if re.search(r"예시|작성예|기재하지않|적용여부를기재|적용여부를명시|명시하여야|적용하지않|미적용|적용제외|예외", compact):
                    uncertain = True
                    continue
                band_context = _norm(text[max(0, line.start()-100):min(end, line.start()+500)])
                stated = re.search(r"(?:본사업|총사업금액|사업금액).{0,15}?(20|40|80)억(?:원)?(미만|이상)", band_context)
                if stated:
                    amounts = [Decimal(v) for v in _prices(rec)["sw_amounts"]]
                    threshold = Decimal(stated[1]) * 100_000_000
                    if not amounts or any((v < threshold) != (stated[2] == "미만") for v in amounts):
                        uncertain = True  # Wrong/ambiguous stated band is not a proven compliant notice.
                        continue
                return {"item": "v20", "value": 0, "evidence": "", "source_evidence": raw,
                        "rule": "현재 SW 사업금액별 참여제한 안내/적용 참조가 존재", "provenance": PROVENANCE, "facts": scope}
            uncertain |= bool(_UNCERTAIN.search(compact))
    # Article3(2) permits either the notice OR RFP. A missing RFP cannot be
    # converted into known absence simply because the notice was observed.
    complete = rec.get("input_completeness") or {}
    dropped = rec.get("dropped_doc_counts") or {}
    if not (complete.get("공고문_실재") is True and complete.get("추출_성공") is True and complete.get("완전관측") is True):
        return None
    if any(int(v or 0) > 0 for v in dropped.values()) or uncertain:
        return None
    primary = [d for d in _docs(rec) if d.get("type") == "공고문"]
    if not primary or any(len(d["text"].strip()) < 200 for d in primary):
        return None
    return {"item": "v20", "value": 1, "evidence": "", "source_evidence": "",
            "rule": "완전관측된 실제 SW 공고·제안요청서 전체에서 사업금액별 참여제한 안내 부재",
            "provenance": PROVENANCE, "facts": scope}


def apply_software_rules(rec, row, product_fact=None):
    out = deepcopy(row)
    correction = software_participation_override(rec, product_fact)
    if correction is not None:
        out["v20"], out["e20"] = correction["value"], ""
    return out
