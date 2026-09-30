"""Optional per-item balanced demonstrations, from original supplied dev only.

This module is inactive unless explicitly called. Labels are never generated or
corrected here. Retrieval excludes self and near-identical full documents using
the same 0.97 criterion as pps_examples. No evaluated-record state is retained.
"""
from __future__ import annotations

import collections
import gzip
import json
import math
import re

from pps_context import COMPILED
from pps_examples import dedup_terms, fingerprint, terms

ITEM_FAMILIES = {
    1: ("eligibility",), 2: ("performance", "budget"),
    3: ("performance", "budget"), 4: ("performance", "eligibility"),
    5: ("region", "budget"), 6: ("region",), 7: ("region",),
    8: ("performance", "region"), 9: ("specification",),
    10: ("production", "product", "enterprise"),
    11: ("enterprise", "product"), 12: ("production", "product"),
    13: ("enterprise", "product"), 14: ("enterprise", "budget"),
    15: ("enterprise", "budget"), 16: ("enterprise", "budget"),
    17: ("enterprise", "budget"), 18: ("enterprise", "budget"),
    19: ("supply",), 20: ("software", "enterprise"),
    21: ("joint",), 22: ("briefing",),
    23: ("briefing", "dates"), 24: ("budget", "region", "contract"),
}


def compact_meta(meta):
    fields = (("법", "적용계약법"), ("업무", "업무구분"),
              ("추정", "입찰추정가격"), ("예산", "배정예산금액"),
              ("계약", "계약방법"), ("낙찰", "낙찰방법"))
    return ";".join(f"{label}={str(meta[key])[:30]}" for label, key in fields if meta.get(key) is not None)


def _clip_span(span, limit, item):
    text = span["text"]
    if len(text) <= limit:
        return {**span}
    if span.get("anchor") == "original_gold":
        start = 0
    else:
        first = None
        for family in ITEM_FAMILIES[item]:
            match = COMPILED[family][1].search(text)
            if match is not None:
                first = match.start()
                break
        start = max(0, min((first or 0) - limit // 3, len(text) - limit))
    return {**span, "start": span["start"] + start,
            "end": span["start"] + start + limit,
            "text": text[start:start + limit], "clipped": True}


def format_item_examples(examples):
    """Each example gives only its queried item's original reference label."""
    return "\n\n".join(
        f"[별개 항목사례 {index}: v{e['item']}={e['label']} | {e['id']}]\n"
        + e["meta"] + "\n"
        + f"원문({e['span']['type']}): " + e["span"]["text"] + "\n"
        + "원본 dev 참조라벨이며 노이즈 가능."
        for index, e in enumerate(examples, 1)
    )


class ItemExampleIndex:
    def __init__(self, path):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        if payload.get("schema_version") != 1:
            raise ValueError("Unsupported item demonstration schema")
        self.examples = payload["examples"]
        self.dedup_sets = [set(e["dedup_terms"]) for e in self.examples]
        self.counts = {}
        self.lengths = {}
        self.average = {}
        self.idf = {}
        for item in range(1, 25):
            counts = [collections.Counter(terms(e["spans"][str(item)]["text"] + " " + compact_meta(e["meta"]))) for e in self.examples]
            lengths = [sum(c.values()) for c in counts]
            df = collections.Counter(t for counter in counts for t in counter)
            size = len(counts)
            self.counts[item] = counts
            self.lengths[item] = lengths
            self.average[item] = sum(lengths) / max(1, size)
            self.idf[item] = {t: math.log(1 + (size - count + .5) / (count + .5)) for t, count in df.items()}

    def retrieve(self, rec, query, items, max_chars=4000):
        """Get one positive and one negative per requested item when they fit.

        ``max_chars`` includes format_item_examples output and source headers.
        Very small budgets retain complete balanced item pairs; they never emit
        a one-sided pair merely to fit. Items are processed in caller order.
        """
        requested = list(dict.fromkeys(int(str(item).removeprefix("v")) for item in items))
        if any(item not in ITEM_FAMILIES for item in requested):
            raise ValueError("Items must be v1..v24")
        if not requested or max_chars <= 0:
            return []
        fp = fingerprint(rec)
        source_terms = set(dedup_terms(rec))
        excluded = set()
        for index, (example, example_terms) in enumerate(zip(self.examples, self.dedup_sets)):
            if example["id"] == rec["id"] or example["fingerprint"] == fp:
                excluded.add(index)
                continue
            if example_terms and min(len(source_terms), len(example_terms)) >= .97 * max(len(source_terms), len(example_terms)):
                intersection = len(source_terms & example_terms)
                if intersection / max(1, len(source_terms) + len(example_terms) - intersection) >= .97:
                    excluded.add(index)
        query_terms = set(terms(query))
        pairs = []
        meta = rec.get("meta") or {}
        for item in requested:
            ranked = {0: [], 1: []}
            for index, example in enumerate(self.examples):
                if index in excluded:
                    continue
                count = self.counts[item][index]
                length = self.lengths[item][index]
                denominator = 1.2 * (.3 + .7 * length / max(1, self.average[item]))
                score = sum(self.idf[item].get(token, 0) * count[token] * 2.2 / (count[token] + denominator) for token in query_terms if token in count)
                # Fixed same-condition preference, based only on original metadata.
                score += 1.5 * (meta.get("적용계약법") == example["meta"].get("적용계약법"))
                score += 1.0 * (meta.get("업무구분") == example["meta"].get("업무구분"))
                label = example["labels"][item - 1]
                ranked[label].append((score, -index, index))
            if not ranked[0] or not ranked[1]:
                continue
            pair = []
            for label in (1, 0):
                score, _, index = max(ranked[label])
                example = self.examples[index]
                pair.append({"id": example["id"], "item": item, "label": label,
                             "meta": compact_meta(example["meta"]),
                             "span": dict(example["spans"][str(item)]),
                             "score": score, "fingerprint": example["fingerprint"]})
            pairs.append(pair)
        # Give all requested item pairs a fair text allowance, keeping excerpts
        # literal. Reduce text before dropping complete pairs from the tail.
        for text_limit in (260, 220, 180, 150, 120, 90, 60):
            output = [{**e, "span": _clip_span(e["span"], text_limit, e["item"])} for pair in pairs for e in pair]
            if len(format_item_examples(output)) <= max_chars:
                return output
        while pairs:
            pairs.pop()
            output = [{**e, "span": _clip_span(e["span"], 60, e["item"])} for pair in pairs for e in pair]
            if len(format_item_examples(output)) <= max_chars:
                return output
        return []
