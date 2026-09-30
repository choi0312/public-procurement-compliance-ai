"""Positive-only v23 calculations from explicit, same-notice calendar fields.

Uses supplied local negotiated-tender rules. No system/current year, IDs,
labels, neighboring notices, inferred opening dates, or learned thresholds.
One-day statutory counting boundary cases abstain rather than guessing.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
import re

from pps_procedure_rules import _negotiated_status
from pps_rules import effective_price


PROVENANCE = ["항목표.json#항목.v23",
              "법령/지방자치단체 입찰시 낙찰자 결정기준.txt#제7장제3절2다",
              "법령/지방자치단체를 당사자로 하는 계약에 관한 법률 시행령.txt#제35조"]
_FULL_DATE = re.compile(r"(?<!\d)(20\d{2})\s*(?:[./-]|년)\s*(\d{1,2})\s*(?:[./-]|월)\s*(\d{1,2})(?!\d)")
_SHORT_DATE = re.compile(r"(?<![\d.])(\d{1,2})\s*[./-]\s*(\d{1,2})(?!\d)")
_WEEKDAY = re.compile(r"^[.일\s]*\(([월화수목금토일])(?:요일)?\)")
_BRIEFING = re.compile(r"(?:현장|사업|과업|제안요청서?)\s*설명(?:회)?")
_DEADLINE = re.compile(r"(?:기술)?제안서(?:및(?:가격)?입찰서)?(?:제출및)?(?:접수|제출)|^접수마감")
_NO_DEADLINE = re.compile(r"평가|발표|개찰|구비서류|제출서류|접수장소|제출장소|자격|확인서|보완|증명|접수완료후")
_UNKNOWN_EVENT = re.compile(r"추후|별도안내|개별안내|개별통보|일정미정|추후공지|개최하지않|생략|갈음")
_NOT_EVENT = re.compile(r"제안서설명회|제안설명회|제안서발표|제안서평가|결과설명|성과설명|사전규격|사전공고")
_NEXT_TOPIC = re.compile(r"^(?:(?:[가-하]|\d{1,2})[.)]|[①-⑳○◦●□■▶※•❍‣-])?\s*(?:제안서?평가|제안평가|개찰|가격입찰|입찰보증|참가자격|제출서류|제출장소|접수장소)")
_PREFIX = re.compile(r"^(?:(?:[가-하]|\d{1,2})[.)]|[①-⑳○◦●□■▶※•❍‣-])\s*")


def _dates(text):
    """Full dates; range endpoints may inherit an explicit preceding year."""
    values, occupied = [], []
    for match in _FULL_DATE.finditer(text):
        try:
            value = date(*(int(match.group(n)) for n in (1, 2, 3)))
        except ValueError:
            return None
        weekday = _WEEKDAY.match(text[match.end():match.end()+14])
        if weekday and "월화수목금토일"[value.weekday()] != weekday.group(1):
            return None
        values.append({"date": value, "start": match.start(), "end": match.end()})
        occupied.append((match.start(), match.end()))
    for match in _SHORT_DATE.finditer(text):
        if any(a <= match.start() < b or a < match.end() <= b for a, b in occupied):
            continue
        preceding = [v for v in values if v["end"] <= match.start()]
        if not preceding:
            continue
        previous = max(preceding, key=lambda v: v["end"])
        bridge = text[previous["end"]:match.start()]
        if len(bridge) > 70 or not re.search(r"[~∼～]|부터", bridge):
            continue
        try:
            value = date(previous["date"].year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
        weekday = _WEEKDAY.match(text[match.end():match.end()+14])
        if weekday and "월화수목금토일"[value.weekday()] != weekday.group(1):
            return None
        if value < previous["date"]:
            return None  # Never guess a New-Year rollover.
        values.append({"date": value, "start": match.start(), "end": match.end()})
    return sorted(values, key=lambda v: v["start"])


def _kind(line):
    compact = re.sub(r"\s+", "", line)
    compact = _PREFIX.sub("", compact)
    if re.search(r"^(?:입찰)?공고(?:기간|일자|게시일|일)(?:[:：]|$)", compact):
        if "공고일로부터" not in compact:
            return "announcement"
    if _NOT_EVENT.search(compact):
        return None
    if _BRIEFING.search(compact):
        return "briefing"
    if _DEADLINE.search(compact) and not _NO_DEADLINE.search(compact):
        return "deadline"
    return None


def _field_candidates(rec):
    candidates = {kind: [] for kind in ("briefing", "deadline", "announcement")}
    for doc in rec.get("docs", []):
        if doc.get("type") != "공고문" or not isinstance(doc.get("text"), str):
            continue
        text = doc["text"]
        lines = list(re.finditer(r"[^\n]+", text))
        for index, line in enumerate(lines):
            kind = _kind(line.group())
            if kind is None:
                continue
            compact_line = re.sub(r"\s+", "", line.group())
            if kind == "briefing" and _UNKNOWN_EVENT.search(compact_line):
                continue
            if kind == "deadline" and not (re.search(r"[:：]|일시|기간|마감", compact_line)
                                            or re.search(r"(?:접수|제출)(?:\[[^\]]+\])?[~∼～]?$", compact_line)):
                continue
            stop = line.end()
            for following in lines[index+1:index+5]:
                if following.end()-line.start() > 500:
                    break
                next_compact = re.sub(r"\s+", "", following.group())
                if _kind(following.group()) is not None or _NEXT_TOPIC.search(next_compact):
                    break
                # A date-bearing line belongs to this field only before another
                # visible numbered event; an 일시/기간 subfield is allowed.
                if _PREFIX.match(next_compact) and not re.search(r"(?:일시|기간|마감)[:：]", next_compact):
                    break
                stop = following.end()
            block = text[line.start():stop]
            if kind == "announcement":
                block = re.split(r"※\s*사전|사전규격|사전공고", block, maxsplit=1)[0]
                stop = line.start()+len(block)
            values = _dates(block)
            if not values:
                continue
            unique = {v["date"] for v in values}
            if kind == "briefing" and len(unique) != 1:
                continue
            if len(unique) > 1 and not re.search(r"[~∼～]|부터", block):
                continue
            chosen = min(values, key=lambda v: v["date"]) if kind == "announcement" else max(values, key=lambda v: v["date"])
            end = max(line.end(), line.start()+chosen["end"])
            # Keep one original source field, including its heading and date.
            source_text = text[line.start():end].strip()
            start = text.find(source_text, line.start(), end)
            if not source_text or len(source_text)>500 or source_text.startswith(("=", "+", "@")):
                continue
            candidates[kind].append({"doc_id": doc["doc_id"], "start": start, "end": start+len(source_text),
                                     "text": source_text, "date": chosen["date"].isoformat()})
    return candidates


def _one_date(fields):
    dates = {field["date"] for field in fields}
    return fields[0] if len(dates) == 1 else None


def _minimum_period(rec):
    facts = effective_price(rec)
    if not facts["reliable"]:
        return None
    values = [Decimal(row["amount"]) for row in facts["body_estimates"]]
    if facts["meta_amount"] is not None:
        values.append(Decimal(facts["meta_amount"]))
    # Reconcile the exact v23 bands independently from v2's 230M band.
    periods = {10 if value < 100_000_000 else 20 if value < 1_000_000_000 else 40 for value in values}
    return next(iter(periods)) if len(periods) == 1 else None


def briefing_date_facts(rec):
    """Return only calendar fields actually observed in this notice."""
    fields = _field_candidates(rec)
    announcement = _one_date(fields["announcement"])
    if announcement is None and not fields["announcement"]:
        posted = str((rec.get("meta") or {}).get("공고게시일자", ""))
        if re.fullmatch(r"20\d{6}", posted):
            try:
                value = date(int(posted[:4]), int(posted[4:6]), int(posted[6:]))
            except ValueError:
                value = None
            # Meta is a fallback only when its year is confirmed by an actual
            # full calendar date in the current notice, never the system year.
            if value and any(field["date"].startswith(str(value.year)+"-") for group in fields.values() for field in group):
                announcement = {"date": value.isoformat(), "source": "meta.공고게시일자"}
    return {"briefings": fields["briefing"], "deadline": _one_date(fields["deadline"]),
            "announcement": announcement, "minimum_period": _minimum_period(rec),
            "ambiguous_deadlines": len({f["date"] for f in fields["deadline"]}) > 1}


def briefing_dates_override(rec):
    """Return a certain positive v23 correction, otherwise abstain.

    Calendar gaps strictly below 7 or 10/20/40 are definitely too short even
    before the excluded-day counting issue. Exact boundaries never trigger.
    Urgent overall publication reductions do not rewrite the separate supplied
    briefing intervals. No negative correction is inferred from missing dates.
    """
    if (rec.get("meta") or {}).get("적용계약법") != "지방계약법" or _negotiated_status(rec) is not True:
        return None
    facts = briefing_date_facts(rec)
    for briefing in facts["briefings"]:
        day = date.fromisoformat(briefing["date"])
        reasons = []
        if facts["announcement"]:
            gap = (day-date.fromisoformat(facts["announcement"]["date"])).days
            if 0 <= gap < 7:
                reasons.append({"interval": "announcement_to_briefing", "calendar_days": gap, "required_days": 7})
        if facts["deadline"] and facts["minimum_period"]:
            gap = (date.fromisoformat(facts["deadline"]["date"])-day).days
            if 0 <= gap < facts["minimum_period"]:
                reasons.append({"interval": "briefing_to_proposal_deadline", "calendar_days": gap,
                                "required_days": facts["minimum_period"]})
        if reasons:
            return {"item": "v23", "value": 1, "evidence": briefing["text"],
                    "doc_id": briefing["doc_id"], "start": briefing["start"], "end": briefing["end"],
                    "rule": "explicit agency-briefing calendar interval is definitely below the supplied minimum",
                    "intervals": reasons, "facts": facts, "provenance": PROVENANCE}
    return None


def apply_briefing_dates(rec, row):
    out = deepcopy(row)
    correction = briefing_dates_override(rec)
    if correction is not None:
        out.update(v23=1, e23=correction["evidence"])
    return out
