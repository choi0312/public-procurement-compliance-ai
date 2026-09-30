"""Retrieval over supplied dev examples only; no trained weights or test state."""
import collections
import gzip
import hashlib
import json
import math
import re


def fingerprint(rec):
    # The identifier is intentionally excluded: repeated text is still the same example.
    text = "\n".join(d["text"] for d in rec["docs"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def terms(text):
    out = []
    for token in re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d{4,}", text.lower()):
        out.append(token)
        if re.fullmatch(r"[가-힣]+", token) and len(token) > 2:
            out.extend(token[i:i+2] for i in range(len(token)-1))
    return out


def dedup_terms(rec):
    """Comparable full-document signature, retaining even short numeric values."""
    text = "\n".join(d["text"] for d in rec["docs"])
    return sorted(set(terms(text)) | {"#" + n for n in re.findall(r"\d+(?:[.,]\d+)*", text)})


class ExampleIndex:
    def __init__(self, path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            self.examples = json.load(f)
        self.dedup_sets = [set(e.get("dedup_terms", [])) for e in self.examples]
        self.counts = [collections.Counter(terms(e["text"] + " " + e["meta"])) for e in self.examples]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df = collections.Counter(t for c in self.counts for t in c)
        n = len(self.examples)
        self.idf = {t: math.log(1 + (n-d+0.5)/(d+0.5)) for t,d in df.items()}

    def retrieve(self, rec, query, k=2):
        if not k:
            return []
        fp = fingerprint(rec)
        full_terms = set(dedup_terms(rec))
        ts = set(terms(query))
        ranked = []
        for i, (e, c, length) in enumerate(zip(self.examples, self.counts, self.lengths)):
            if e["id"] == rec["id"] or e["fingerprint"] == fp:
                continue
            # Compare the SAME full-document representation, not a 4.5k query
            # against a 2k demonstration. Shortened texts hide near duplicates.
            candidate_terms = self.dedup_sets[i]
            # Length ratio upper-bounds Jaccard and avoids most intersections.
            if candidate_terms and min(len(full_terms), len(candidate_terms)) >= 0.97 * max(len(full_terms), len(candidate_terms)):
                intersection = len(full_terms & candidate_terms)
                jaccard = intersection / max(1, len(full_terms) + len(candidate_terms) - intersection)
                if jaccard >= 0.97:
                    continue
            den = 1.2*(1-0.7+0.7*length/max(1,self.avg))
            score = sum(self.idf.get(t,0)*c[t]*2.2/(c[t]+den) for t in ts if t in c)
            ranked.append((score, i))
        return [self.examples[i] for _, i in sorted(ranked, reverse=True)[:k]]


def format_examples(examples):
    lines = []
    for i,e in enumerate(examples,1):
        hits = ",".join(f"v{j+1}" for j,v in enumerate(e["labels"]) if v) or "없음"
        lines.append(f"[별개 참고사례 {i}]\n{e['meta']}\n{e['text']}\n정답 위반 항목: {hits}. 나머지 항목은0.")
    return "\n\n".join(lines)
