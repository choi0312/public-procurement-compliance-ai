"""Per-record facts and provided competitive-product retrieval; no learned state.

Sources: PPS_DATA_DIR/법령패키지/중기부고시/중기부고시_경쟁제품_세부품명.csv.
Retrieval candidates are not definitive legal classifications. The helper never
shares evaluated records, predictions or statistics across calls.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PRODUCT_RELATIVE = Path("법령패키지/중기부고시/중기부고시_경쟁제품_세부품명.csv")
_CODE_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
_TITLE_RE = re.compile(r"(?:건\s*명|용\s*역\s*명|사\s*업\s*명|과\s*업\s*명|입\s*찰\s*명|품\s*명)\s*[:：]?")
_MONEY_RE = re.compile(r"예\s*산|기\s*초\s*금\s*액|추\s*정\s*가\s*격|용\s*역\s*금\s*액|사\s*업\s*금\s*액|총\s*사\s*업\s*비")
_DATE_RE = re.compile(r"공\s*고\s*기\s*간|제\s*출\s*마\s*감|접\s*수|설\s*명\s*회|공\s*고\s*일|개\s*찰\s*일")
_CALENDAR_DATE_RE = re.compile(r"(?:20\d{2}\s*[.\-/년]\s*\d{1,2}|\d{1,2}\s*월\s*\d{1,2}|20\d{6})")
_AMOUNT_RE = re.compile(r"(?:\d[\d,.]*\s*(?:억|만|천|백|원)|\d{1,3}(?:,\d{3})+|\d{5,})")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", str(value or "").lower())


def _grams(value: str) -> set[str]:
    return {value[i : i + 3] for i in range(max(0, len(value) - 2))}


def _name_present(name: str, normalized_text: str, tokens: set[str]) -> bool:
    # Provided products include single-letter names such as "표" and "요".
    # Unbounded substring matching would retrieve these for almost every notice.
    if not name or len(name) == 1:
        # Single-letter products require a code match; "표 1" is usually a
        # document table and "요" commonly appears in unrelated prose.
        return False
    if len(name) >= 4:
        return name in normalized_text
    return name in tokens


def _number(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "미확인"
    try:
        n = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return str(value)[:60]
    return f"{n:,.0f}원" if n.is_integer() else f"{n:,.2f}원"


def _positive_meta_krw(value: Any) -> Decimal | None:
    """Parse explicit numeric KRW, never guessed Korean or foreign units.

    Official JSON values are integer won. Numeric strings (optionally grouped
    by thousands or followed by '원') are tolerated, but '2.3억원', unknown,
    Boolean, zero and negative sentinel-like values produce no arithmetic.
    """
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    raw = str(value).strip()
    if isinstance(value, str):
        if raw.endswith("원"):
            raw = raw[:-1].strip()
        if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
            return None
    try:
        amount = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _lines(rec: dict) -> list[str]:
    result = []
    for doc in rec.get("docs", []):
        text = doc.get("text", "")
        if isinstance(text, str):
            result.extend(text.splitlines())
    return result


def _snippets(lines: list[str], pattern: re.Pattern, limit: int, width: int = 180) -> list[str]:
    """Include wrapped dates/amounts from the next two lines, deduplicated."""
    found = []
    seen = set()
    for idx, line in enumerate(lines):
        if not pattern.search(line):
            continue
        snippet = " ".join(x.strip() for x in lines[idx : idx + 3] if x.strip())
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not re.search(r"\d", snippet) and pattern is not _TITLE_RE:
            continue
        if pattern is _DATE_RE and not _CALENDAR_DATE_RE.search(snippet):
            continue
        if pattern is _MONEY_RE and not _AMOUNT_RE.search(snippet):
            continue
        snippet = snippet[:width]
        normalized = _norm(snippet)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        found.append(snippet)
        if len(found) >= limit:
            break
    return found


class ProvidedFacts:
    """Immutable reference lookup plus deterministic, record-local facts."""

    def __init__(self, data_dir: str | Path):
        path = Path(data_dir) / PRODUCT_RELATIVE
        self.source = str(PRODUCT_RELATIVE)
        self.available = path.is_file()
        self.rows: list[dict[str, str]] = []
        self._by_gram: dict[str, set[int]] = defaultdict(set)
        self._cores: list[str] = []
        self._names: list[str] = []
        if not self.available:
            return
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"세부품명번호", "세부품명", "특이사항"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"Provided competitive-product CSV lacks {required}")
            for row in reader:
                row = {k: str(v or "").strip() for k, v in row.items() if k}
                self.rows.append(row)
                name = _norm(row["세부품명"])
                core = name
                for suffix in ("서비스", "용역", "제품", "물품"):
                    if core.endswith(suffix) and len(core) - len(suffix) >= 4:
                        core = core[: -len(suffix)]
                        break
                self._names.append(name)
                self._cores.append(core)
                for gram in _grams(core):
                    self._by_gram[gram].add(len(self.rows) - 1)

    def service_catalog(self, rec: dict) -> str:
        """Complete service rows from the supplied snapshot, never outside law."""
        if not self.available:return ""
        rows=[r for r in self.rows if "서비스" in r["세부품명"] or "용역" in r["세부품명"]]
        return "[제공 경쟁제품 CSV의 서비스·용역 명칭 전체와 조건]\n"+"\n".join(
            f"{r['세부품명번호']} {r['세부품명']}: {r['특이사항'] or '별도 조건 없음'}" for r in rows)+"\n실제 구매대상을 이 목록과 대조한다. 운영위탁서비스는 SW 범주이며 일반 행사운영을 뜻하지 않는다. 기타행사·국제행사 10억원 미만과 축제 3억원 미만 조건은 서로 다르다. 증명서 코드만으로 실제 과업을 분류하지 않는다."

    def code_membership(self, rec: dict) -> str:
        """Exact registry membership of explicit product codes, never a label."""
        if not self.available:return ""
        codes=set(_CODE_RE.findall(str((rec.get("meta") or {}).get("세부품명번호목록") or "")))
        for doc in rec.get("docs",[]):
            for match in re.finditer(r"세부\s*품명[^\n]{0,100}",doc.get("text", "")):
                codes.update(_CODE_RE.findall(match.group()))
        if not codes:return ""
        by_code={r["세부품명번호"]:r for r in self.rows}
        lines=["[명시된 품명코드의 제공 경쟁제품 CSV 정확 조회; 실제 구매대상 여부는 본문과 별도 확인]"]
        for code in sorted(codes)[:10]:
            row=by_code.get(code)
            if row:lines.append(f"{code}: CSV등재, 품명={row['세부품명']}, 적용조건={row['특이사항'] or '별도 조건 없음'}")
            else:lines.append(f"{code}: 제공 경쟁제품 CSV에 해당 코드 없음.")
        return "\n".join(lines)[:1400]

    def candidates(self, rec: dict, limit: int = 6) -> list[dict[str, Any]]:
        """Rank candidate CSV rows; certificate-only matches stay explicitly tentative."""
        if not self.available:
            return []
        meta = rec.get("meta", {}) or {}
        lines = _lines(rec)
        docs_text = "\n".join(lines)
        names_text = str(meta.get("세부품명번호목록") or "")
        norm_meta = _norm(names_text)
        norm_doc = _norm(docs_text)
        meta_codes = set(_CODE_RE.findall(names_text))
        doc_codes = set(_CODE_RE.findall(docs_text))
        title_text = " ".join(_snippets(lines, _TITLE_RE, limit=6, width=150))
        norm_title = _norm(title_text)
        title_tokens = set(re.findall(r"[가-힣a-z0-9]+", title_text.lower()))
        meta_tokens = set(re.findall(r"[가-힣a-z0-9]+", names_text.lower()))
        doc_tokens = set(re.findall(r"[가-힣a-z0-9]+", docs_text.lower()))
        # Fuzzy matching is confined to title-like spans and provided meta names;
        # broad attachment prose would produce many incidental vocabulary hits.
        query_grams = _grams(norm_title + norm_meta)
        fuzzy_ids: set[int] = set()
        for gram in query_grams:
            fuzzy_ids.update(self._by_gram.get(gram, ()))
        ranked = []
        for index, row in enumerate(self.rows):
            code = row["세부품명번호"]
            name = self._names[index]
            core = self._cores[index]
            reasons = []
            score = 0.0
            if code in meta_codes:
                score = 120.0
                reasons.append("meta 코드 일치(실제 과업 대조 필요)")
            if code in doc_codes:
                score = max(score, 100.0)
                reasons.append("문서 코드 일치(직생증명서 코드일 수 있음)")
            if _name_present(name, norm_title, title_tokens):
                score = max(score, 90.0)
                reasons.append("건명/품명 주변 문자이름 일치")
            elif _name_present(name, norm_meta, meta_tokens):
                score = max(score, 85.0)
                reasons.append("meta 문자이름 일치")
            elif _name_present(name, norm_doc, doc_tokens):
                score = max(score, 70.0)
                reasons.append("문서 문자이름 일치(증명서 명칭일 수 있음)")
            if len(core) >= 4 and core in norm_title and core != name:
                score = max(score, 65.0)
                reasons.append("건명/품명 주변 핵심 문자이름 일치")
            if not reasons and index in fuzzy_ids and len(core) >= 5:
                grams = _grams(core)
                overlap = len(grams & query_grams) / max(1, len(grams))
                # A near-complete core-name overlap is only a weak search lead.
                if overlap >= 0.75 and len(grams & query_grams) >= 3:
                    score = 30.0 + overlap
                    reasons.append("건명/meta 문자이름 부분중첩(약한 검색 후보)")
            if reasons:
                ranked.append({"row": dict(row), "reason": "; ".join(reasons), "score": score})
        ranked.sort(key=lambda x: (-x["score"], x["row"]["세부품명번호"]))
        return ranked[: max(0, limit)]

    def numeric_bands(self, rec: dict) -> str:
        """Optional meta-only arithmetic, not included by ``describe``.

        The reference amounts come from the supplied item table/law package.
        This reports comparisons only: applicability, VAT handling and final
        labels still require reading this record's documents. A missing or
        invalid estimate never falls back to allocated budget or other keys.
        """
        meta = rec.get("meta", {})
        if not isinstance(meta, dict):
            return ""
        price = _positive_meta_krw(meta.get("입찰추정가격"))
        if price is None:
            return ""
        comparisons = [
            ("P<100,000,000원", price < 100_000_000),
            ("100,000,000원≤P<230,000,000원", 100_000_000 <= price < 230_000_000),
            ("P≥150,000,000원", price >= 150_000_000),
            ("P≥230,000,000원", price >= 230_000_000),
            ("P≥300,000,000원", price >= 300_000_000),
            ("P≥330,000,000원", price >= 330_000_000),
            ("P≥500,000,000원", price >= 500_000_000),
        ]
        shown_price = format(price, ",f")
        if "." in shown_price:
            shown_price = shown_price.rstrip("0").rstrip(".")
        return (
            "[메타 금액 산술구간: 최종판정 아님]\n"
            + "P=meta.입찰추정가격=" + shown_price + "원.\n"
            + "; ".join(expression + "=" + ("참" if result else "거짓") for expression, result in comparisons)
            + "\n현재 발주 추정가격의 단순 비교이며 요구실적금액의 비교가 아님. "
            + "본문에 명시된 금액·부가세 기준과 대조할 것. "
            + "기관·업무별 적용기준 및 예외는 별도 확인하며, SW의 VAT포함 사업금액으로 대체하지 말 것."
        )

    def describe(self, rec: dict) -> str:
        """Return <=3500 characters; facts and search hints, never final labels."""
        meta = rec.get("meta", {}) or {}
        lines = _lines(rec)
        parts = ["[제공 자료 기반 사실·검색 후보: 판정이 아님]"]
        parts.append(
            "메타: 적용계약법=" + str(meta.get("적용계약법", "미확인"))
            + "; 업무=" + str(meta.get("업무구분", "미확인"))
            + "; 계약방법=" + str(meta.get("계약방법", "미확인"))
            + "; 낙찰방법=" + str(meta.get("낙찰방법", "미확인"))
            + "; 소관=" + str(meta.get("소관구분", "미확인"))
        )
        parts.append(
            "메타 금액: 입찰추정가격=" + _number(meta.get("입찰추정가격"))
            + "; 배정예산금액=" + _number(meta.get("배정예산금액"))
            + ". 추정가격과 VAT포함 예산은 다른 값일 수 있음. 본문과 기준을 맞춰 비교."
        )
        parts.append(
            "메타 시점: 공고게시=" + str(meta.get("공고게시일자", "미확인"))
            + "; 개찰예정=" + str(meta.get("개찰예정일자", "미확인"))
            + "; 긴급=" + str(meta.get("긴급공고여부", "미확인"))
            + ". 개찰예정은 제안서 접수마감이 아님."
        )
        parts.append(
            "메타 범위: 지역제한=" + str(meta.get("지역제한여부", "미확인"))
            + "; 지역=" + str(meta.get("제한지역코드목록") or "미입력")[:160]
            + "; 공동도급=" + str(meta.get("공동도급구성방식") or "미입력")
            + "; 정보화=" + str(meta.get("정보화사업여부", "미확인"))
            + ". 본문과 대조하며 메타만으로 위반을 확정하지 않음."
        )
        completeness = rec.get("input_completeness")
        if isinstance(completeness, dict) and any(v is False for v in completeness.values()):
            parts.append("입력완전성 주의: " + str(completeness)[:220] + "; 미관측과 부재를 구별.")
        titles = _snippets(lines, _TITLE_RE, 3, 150)
        if titles:
            parts.append("본문 건명/품명 주변: " + " | ".join(titles))
        parts.append("경쟁제품은 실제 구매과업→CSV 후보→특이사항 순서로 판정. 증명서 이름·번호만으로 과업을 확정하지 말 것. 검색결과 없음도 일반제품 확정이 아님.")
        if not self.available:
            parts.append("제공 경쟁제품CSV를 찾지 못함: 경쟁제품 여부 미확인.")
        else:
            candidates = self.candidates(rec)
            for candidate in candidates:
                row = candidate["row"]
                parts.append(
                    "CSV후보 " + row["세부품명번호"] + " " + row["세부품명"]
                    + "; 이유=" + candidate["reason"]
                    + "; 특이사항=" + (row["특이사항"] or "별도표시없음")
                )
            if not candidates:
                parts.append("CSV 검색후보 없음(단어 불일치 가능; 일반제품으로 자동판정 금지).")
        money = _snippets(lines, _MONEY_RE, 3, 160)
        dates = _snippets(lines, _DATE_RE, 5, 170)
        if money:
            parts.append("본문 금액 주변(검토용): " + " | ".join(money))
        if dates:
            parts.append("본문 공고/설명회/접수 주변(검토용): " + " | ".join(dates))
        result = "\n".join(parts)
        if len(result) > 3500:
            result = result[:3470] + "\n[길이제한: 뒤의 사실 후보 일부 생략]"
        return result
