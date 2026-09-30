"""Select exact source spans for procurement review, without learned parameters.

``max_chars`` bounds the sum of selected source text lengths. Formatting adds
short source labels, so callers must still enforce the model's token budget.
Offsets refer to the input string verbatim, including its Unicode normalization.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List

SPAN_CHARS = 450
STRIDE_CHARS = 240

# These are task vocabulary, not labels or an external procurement corpus.
FAMILIES = {
    "eligibility": (4.0, r"참가\s*자격|입찰\s*참가|응모\s*자격|신청\s*자격|참여\s*자격|입찰에\s*참가"),
    "performance": (4.2, r"실적|준공|납품\s*금액|수행\s*금액|최근\s*\d+\s*년"),
    "region": (4.0, r"\[지역:|단위\s*=\s*기초|주된\s*영업소|본점|본사\s*소재|지역\s*제한|인접|관할"),
    "enterprise": (4.2, r"중소\s*기업|소\s*기업|소상공인|중\s*기업|대\s*기업|중견\s*기업|판로\s*지원|비영리"),
    "production": (4.8, r"직접\s*생산|직생|생산\s*확인\s*증명"),
    "product": (3.0, r"세부\s*품명|물품\s*분류|경쟁\s*제품|특이\s*사항|구매\s*대상|구매\s*품목"),
    "software": (3.8, r"소프트웨어|정보화\s*사업|상호\s*출자|참여\s*제한|사업\s*금액"),
    "joint": (4.0, r"공동\s*(?:수급|도급|이행|계약)|구성원|출자\s*비율|최소\s*지분|분담\s*비율|지분율"),
    "briefing": (4.8, r"현장\s*설명|사업\s*설명|제안\s*요청\s*설명|설명회|필수\s*참석"),
    "budget": (3.6, r"사업\s*예산|추정\s*가격|추정\s*금액|기초\s*금액|배정\s*예산|총\s*사업비|부가\s*(?:세|가치세)|사업\s*금액"),
    "contract": (2.2, r"계약\s*방법|낙찰\s*방법|제한\s*경쟁|일반\s*경쟁|수의\s*계약|견적\s*제출|협상에|협상에\s*의한|국가를\s*당사자|지방자치단체를\s*당사자"),
    "supply": (4.0, r"공급\s*확약|기술\s*지원\s*확약|제조사\s*확약|물품\s*공급"),
    "specification": (3.8, r"모델\s*(?:명|번호)?|제조\s*(?:사|업체)|특정\s*(?:제품|규격|상표)|제품\s*명|동등\s*(?:이상|품)|동급|상표|브랜드"),
    "dates": (1.4, r"공고\s*일|공고\s*기간|입찰\s*기간|제출\s*기한|접수\s*기간|개찰\s*일|입찰\s*마감|제안서\s*제출"),
}
COMPILED = {name: (weight, re.compile(pattern)) for name, (weight, pattern) in FAMILIES.items()}
MODEL_CODE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Za-z]{1,12}[-_ ]?\d[A-Za-z0-9_.-]{1,20}|[A-Z]{2,12}[-_]\d[A-Za-z0-9_.-]{0,20})(?![A-Za-z0-9])")
QUALIFIER = re.compile(r"보유|소지|갖춘|제한|이상|미만|초과|이내|이하|예외|제외|인정|가능|불가|한정|한함|하여야|해야|단,|다만|또는|모두|각각")
SPEC_TYPES = {"규격서", "과업지시서", "제안요청서"}


def _windows(text: str):
    """Overlapping exact windows, preferring nearby paragraph/sentence endings."""
    start = 0
    while start < len(text):
        end = min(start + SPAN_CHARS, len(text))
        if end < len(text):
            # Keep enough overlap for a clause crossing a paragraph boundary.
            floor = start + 330
            endings = [text.rfind("\n", floor, end), text.rfind(". ", floor, end)]
            boundary = max(endings)
            if boundary >= floor:
                end = boundary + 1
        if text[start:end].strip():
            yield start, end
        if end == len(text):
            break
        start += min(STRIDE_CHARS, max(1, end - start - 100))


def _features(text: str, doc_type: str) -> Dict[str, float]:
    features = {}
    for family, (weight, pattern) in COMPILED.items():
        hits = len(pattern.findall(text))
        if hits:
            features[family] = weight * (1 + min(hits - 1, 4) * 0.18)
    if doc_type in SPEC_TYPES and MODEL_CODE.search(text):
        features["specification"] = features.get("specification", 0.0) + 3.0
    return features


def _overlap_length(start: int, end: int, intervals) -> int:
    clipped = sorted((max(start, a), min(end, b)) for a, b in intervals if a < end and b > start)
    total = 0
    last = start
    for a, b in clipped:
        a = max(a, last)
        if a < b:
            total += b - a
            last = b
    return total


def select_spans(rec: Dict[str, Any], max_chars: int = 18000) -> List[Dict[str, Any]]:
    """Return deterministic <=450-character exact source spans for one record.

    Selection uses only this record and static task vocabulary. It never consults
    development labels, other records, global corpus statistics or predictions.
    """
    max_chars = int(max_chars)
    if max_chars <= 0:
        return []
    docs = rec.get("docs") or []
    candidates = []
    for doc_index, doc in enumerate(docs):
        text = doc.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        doc_type = str(doc.get("type", "기타"))
        for start, end in _windows(text):
            chunk = text[start:end]
            features = _features(chunk, doc_type)
            score = sum(features.values())
            if features:
                score += min(3.0, len(QUALIFIER.findall(chunk)) * 0.25)
            if doc_type == "공고문":
                score += 1.0
            elif doc_type in SPEC_TYPES:
                score += 0.7
            candidates.append({
                "doc_index": doc_index,
                "doc_id": str(doc.get("doc_id", "")),
                "type": doc_type,
                "start": start,
                "end": end,
                "text": chunk,
                "features": features,
                "score": score,
            })
    if not candidates:
        return []

    # Reserve some output space for overlapping bridge windows after selected
    # intervals are merged. Ranking operates on unique source characters so
    # heavily overlapping candidates cannot consume the entire context budget.
    source_budget = max_chars if max_chars < 1000 else int(max_chars * 0.88)
    selected = []
    selected_ids = set()
    intervals = defaultdict(list)
    family_counts = Counter()
    doc_counts = Counter()
    used = 0

    def add(index, allow_cut=False):
        nonlocal used
        if index in selected_ids:
            return False
        candidate = candidates[index]
        remaining = source_budget - used
        overlap = _overlap_length(candidate["start"], candidate["end"], intervals[candidate["doc_index"]])
        marginal = len(candidate["text"]) - overlap
        if marginal > remaining:
            if not allow_cut or remaining <= 0:
                return False
            candidate = dict(candidate)
            candidate["text"] = candidate["text"][:remaining]
            candidate["end"] = candidate["start"] + remaining
        selected.append(candidate)
        selected_ids.add(index)
        used += len(candidate["text"]) - _overlap_length(candidate["start"], candidate["end"], intervals[candidate["doc_index"]])
        intervals[candidate["doc_index"]].append((candidate["start"], candidate["end"]))
        family_counts.update(candidate["features"].keys())
        doc_counts[candidate["doc_index"]] += 1
        return True

    # Always expose actual notice content, including its purpose and amounts.
    notice_indices = [i for i, c in enumerate(candidates) if c["type"] == "공고문" and c["start"] == 0]
    if not notice_indices:
        notice_indices = [0]
    for index in notice_indices:
        add(index, allow_cut=not selected)

    # Reserve one strong clause per task family. Family order prioritizes clauses
    # commonly absent from document introductions; it is independent of dev IDs.
    family_order = ("briefing", "specification", "production", "performance", "region", "enterprise", "joint", "supply", "budget", "eligibility", "software", "product", "contract", "dates")
    for family in family_order:
        ranked = sorted(
            (i for i, c in enumerate(candidates) if family in c["features"]),
            key=lambda i: (
                -candidates[i]["features"][family],
                -candidates[i]["score"],
                candidates[i]["doc_index"], candidates[i]["start"],
            ),
        )
        if family_counts[family]:
            continue
        for index in ranked:
            if add(index):
                break

    # Keep relevant attachment coverage even if another document has the same
    # vocabulary. This exposes technical restrictions late in specifications.
    for doc_index, doc in enumerate(docs):
        if doc_counts[doc_index] or doc.get("type") == "공고문":
            continue
        ranked = sorted(
            (i for i, c in enumerate(candidates) if c["doc_index"] == doc_index and c["features"]),
            key=lambda i: (-candidates[i]["score"], candidates[i]["start"]),
        )
        for index in ranked:
            if add(index):
                break

    # Greedy diversified completion; overlap is allowed but receives a penalty.
    # This retains enough neighboring text for exceptions and evidence spans.
    while used < source_budget:
        best_index, best_value = None, -1.0
        for i, c in enumerate(candidates):
            if i in selected_ids:
                continue
            overlap = _overlap_length(c["start"], c["end"], intervals[c["doc_index"]])
            if len(c["text"]) - overlap > source_budget - used:
                continue
            novel = 1 - overlap / len(c["text"])
            if novel <= 0:
                continue
            family_score = sum(value / (1 + 0.16 * family_counts[name]) for name, value in c["features"].items())
            intro = 3.0 if c["type"] == "공고문" and c["start"] < 1400 else 0.0
            diversity = 1.2 / (1 + doc_counts[c["doc_index"]])
            value = (family_score + intro + diversity + 0.2) * (0.35 + 0.65 * novel)
            if value > best_value:
                best_index, best_value = i, value
        if best_index is None:
            break
        add(best_index)

    # Compact redundant windows into source intervals, then split them at nearby
    # natural boundaries. This retains much more distinct source material than
    # repeatedly paying for the same 200-character overlap.
    compact = []
    for doc_index, source_intervals in intervals.items():
        merged = []
        for start, end in sorted(source_intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        doc = docs[doc_index]
        for begin, finish in merged:
            cursor = begin
            while cursor < finish:
                end = min(cursor + SPAN_CHARS, finish)
                if end < finish:
                    boundary = doc["text"].rfind("\n", cursor + 330, end)
                    if boundary >= cursor + 330:
                        end = boundary + 1
                compact.append({"doc_index": doc_index, "doc_id": str(doc.get("doc_id", "")), "type": str(doc.get("type", "기타")), "start": cursor, "end": end, "text": doc["text"][cursor:end]})
                cursor = end
    used_output = sum(len(c["text"]) for c in compact)
    # Add highest-value original windows crossing compact boundaries while the
    # reserved budget allows it. Evidence remains one exact source substring.
    for candidate in sorted(selected, key=lambda c: (-c["score"], c["doc_index"], c["start"])):
        if used_output + len(candidate["text"]) > max_chars:
            continue
        if any(c["doc_index"] == candidate["doc_index"] and c["start"] <= candidate["start"] and candidate["end"] <= c["end"] for c in compact):
            continue
        compact.append(candidate)
        used_output += len(candidate["text"])
    selected = compact
    selected.sort(key=lambda c: (c["type"] != "공고문", c["doc_index"], c["start"], c["end"]))
    return [
        {"sid": f"s{number:03d}", **{key: c[key] for key in ("doc_id", "type", "start", "end", "text")}}
        for number, c in enumerate(selected, 1)
    ]


def formatted_context(spans: List[Dict[str, Any]]) -> str:
    """Render span IDs and source locations without altering source text."""
    return "\n\n".join(
        f"[{s['sid']} | {s['type']} | {s['doc_id']} | {s['start']}:{s['end']}]\n{s['text']}"
        for s in spans
    )


def select_spans_compact(rec: Dict[str, Any], max_chars: int = 18000) -> List[Dict[str, Any]]:
    """Preserve selected source coverage with <=10% repeated bridge characters.

    The original selector remains unchanged for reproducible comparisons. This
    variant merges its coverage, emits disjoint exact chunks, then spends at
    most 10% of the *actual unique source length* on high-value bridge windows.
    A short record therefore stays short even under a large context budget.
    """
    original = select_spans(rec, max_chars=max_chars)
    if not original:
        return []
    docs = rec.get("docs") or []
    by_doc = {str(d.get("doc_id", "")): (index, d) for index, d in enumerate(docs)}
    intervals = defaultdict(list)
    for span in original:
        intervals[span["doc_id"]].append((span["start"], span["end"]))
    compact = []
    for doc_id, ranges in intervals.items():
        doc_index, doc = by_doc[doc_id]
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for begin, finish in merged:
            cursor = begin
            while cursor < finish:
                end = min(cursor + SPAN_CHARS, finish)
                if end < finish:
                    boundary = doc["text"].rfind("\n", cursor + 330, end)
                    if boundary >= cursor + 330:
                        end = boundary + 1
                compact.append({"doc_index": doc_index, "doc_id": doc_id, "type": str(doc.get("type", "기타")), "start": cursor, "end": end, "text": doc["text"][cursor:end]})
                cursor = end
    unique_chars = sum(len(span["text"]) for span in compact)
    bridge_budget = min(max_chars - unique_chars, int(unique_chars * 0.10))
    candidates = sorted(original, key=lambda s: (-sum(_features(s["text"], s["type"]).values()), by_doc[s["doc_id"]][0], s["start"], s["end"]))
    for span in candidates:
        if len(span["text"]) > bridge_budget:
            continue
        if any(c["doc_id"] == span["doc_id"] and c["start"] <= span["start"] and span["end"] <= c["end"] for c in compact):
            continue
        compact.append({**span, "doc_index": by_doc[span["doc_id"]][0]})
        bridge_budget -= len(span["text"])
    compact.sort(key=lambda s: (s["type"] != "공고문", s["doc_index"], s["start"], s["end"]))
    return [
        {"sid": f"s{number:03d}", **{key: span[key] for key in ("doc_id", "type", "start", "end", "text")}}
        for number, span in enumerate(compact, 1)
    ]
