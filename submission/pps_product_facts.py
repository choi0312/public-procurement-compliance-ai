"""Conservative actual-product classification from supplied CSV and one notice.

Registration/certificate codes alone never establish the actual purchase.
Names in purchase fields, task titles, and narrowly defined task paraphrases
identify candidates. Every supplied special condition must be decided or the
result is unknown. No labels, IDs, training state, or external data are read.
"""
from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path

from pps_facts import PRODUCT_RELATIVE, _positive_meta_krw
from pps_rules import _qualification_sections, effective_price


_CODE = re.compile(r"(?<!\d)\d{10}(?!\d)")
_FIELD = re.compile(r"(?:사\s*업\s*명|과\s*업\s*명|용\s*역\s*명|입\s*찰\s*(?:건\s*명|명)|계\s*약\s*건\s*명|건\s*명|품\s*명|구\s*입\s*내\s*역|구\s*매\s*품\s*목|용\s*역\s*내\s*용|사\s*업\s*내\s*용)\s*[:：|]?")
_OTHER_FIELD = re.compile(r"(?:과업|사업|용역|계약)(?:기간|개요)|예산액|기초금액|총사업비|사업금액|입찰방법|등록마감일시|제안서평가일(?:예정)?|관리번호|행사(?:일|장소)|납품기한")
_NOT_PURCHASE = re.compile(r"직접\s*생산|확인\s*증명서|확인서|참가\s*자격|등록\s*한\s*(?:자|업체)|업종\s*코드|배점|평가\s*항목|과거\s*실적")
_ACTION = re.compile(r"대행|기획|운영|위탁")
_SW_OBJECT = re.compile(r"(?:정보|전산|경영정보|학습분석|행정|통합관리|출입통제)(?:시스템|체계)|소프트웨어|홈페이지|누리집|웹사이트")
_SW_ACTION = re.compile(r"구축|개발|고도화|운영|유지보수|유지관리|개편|개선")
_SCOPE_MIX = re.compile(r"분담이행|소프트웨어사업과타사업|sw사업과타사업")


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", str(value or "").lower())


def _docs(rec):
    return [d for d in rec.get("docs", []) if isinstance(d, dict) and isinstance(d.get("text"), str)]


def _actual_fields(rec) -> list[dict]:
    result = []
    for doc in _docs(rec):
        if doc.get("type") not in {"공고문", "규격서", "과업지시서", "제안요청서"}:
            continue
        text = doc["text"]
        sections = _qualification_sections(text)
        lines = list(re.finditer(r"[^\n]+", text))
        for i, line in enumerate(lines):
            if any(a <= line.start() < b for a, b in sections):
                continue
            raw = line.group()
            if _NOT_PURCHASE.search(raw):
                continue
            if not _FIELD.search(raw):
                continue
            # Include short table/wrapped values, but stop before any qualifier
            # or a separate named field. A required certificate is not a title.
            end = line.end()
            # Common PDF tables list their column headings, then the first
            # row. Only a title column may cross these known empty headings;
            # stop at its first substantive task-title value.
            if _norm(_FIELD.sub("", raw)) == "":
                for following in lines[i + 1:i + 9]:
                    following_raw = following.group().strip()
                    compact = _norm(following_raw)
                    if not compact or _OTHER_FIELD.fullmatch(compact) or re.fullmatch(r"입찰\d+", compact):
                        continue
                    if len(re.findall(r"[가-힣]", following_raw)) >= 6 and re.search(r"용역|구매|구축|대행|개발|서비스|유지보수|유지관리", compact) and not _NOT_PURCHASE.search(following_raw):
                        value = text[line.start():following.end()].strip()
                        result.append({"doc_id": doc.get("doc_id", ""), "text": value,
                                       "type": doc.get("type"), "start": line.start()})
                    break
            for following in lines[i + 1:i + 4]:
                if _NOT_PURCHASE.search(following.group()) or _FIELD.search(following.group()) or _OTHER_FIELD.search(_norm(following.group())):
                    break
                if len(text[line.start():end].strip()) >= 90 or following.end() - line.start() > 240:
                    break
                end = following.end()
            value = text[line.start():end].strip()
            result.append({"doc_id": doc.get("doc_id", ""), "text": value,
                           "type": doc.get("type"), "start": line.start()})
    # Keep enough declared product fields for mixed-product detection, without
    # using secondary content as statistical context for another record.
    unique = {}
    for row in result:
        unique.setdefault(_norm(row["text"]), row)
    return list(unique.values())


def _prices(rec) -> dict:
    meta = rec.get("meta", {}) or {}
    p = _positive_meta_krw(meta.get("입찰추정가격"))
    b = _positive_meta_krw(meta.get("배정예산금액"))
    parsed = effective_price(rec)
    p_values = ([p] if p is not None else []) + [Decimal(v["amount"]) for v in parsed["body_estimates"]]
    # Supplied SW directive Article3(1)3 defines B=P+VAT. Both explicit public
    # amounts must agree on the relevant band; no arbitrary budget substitution.
    values = ([b] if b is not None else []) + [v * Decimal("1.1") for v in p_values]
    bands = {x < Decimal("2000000000") for x in values}
    return {"price": p, "price_values": p_values, "price_reliable": parsed["reliable"],
            "budget": b, "sw_below_20eok": next(iter(bands)) if len(bands) == 1 and parsed["reliable"] else None,
            "sw_amounts": [str(x) for x in values]}


class ProvidedProductClassifier:
    def __init__(self, data_dir):
        path = Path(data_dir) / PRODUCT_RELATIVE
        self.available = path.is_file()
        self.rows = {}
        if self.available:
            with path.open(encoding="utf-8-sig", newline="") as f:
                self.rows = {r["세부품명번호"]: dict(r) for r in csv.DictReader(f)
                             if _CODE.fullmatch(r["세부품명번호"])}

    def _condition(self, row, rec, actual_text, all_text, prices):
        condition = row.get("특이사항", "").strip()
        compact = _norm(condition)
        p = prices["price"]
        if not condition:
            return "competitive", "CSV 특이사항 없음"
        m = re.fullmatch(r"추정가격(\d+)억원미만에한함", compact)
        if m:
            if not prices["price_reliable"]:
                return "unknown", "CSV 추정가격 금액조건 확인 불가"
            threshold = Decimal(m.group(1)) * 100_000_000
            bands = {v < threshold for v in prices["price_values"]}
            if len(bands) != 1:
                return "unknown", "본문/메타 추정가격이 CSV 조건 경계에서 불일치"
            return ("competitive" if next(iter(bands)) else "general"), f"CSV P<{threshold}원; 현재 P={p or prices['price_values'][0]}원"
        if compact == "소프트웨어진흥법제48조적용":
            if _SCOPE_MIX.search(_norm(str((rec.get("meta") or {}).get("공동도급구성방식")) + all_text)):
                return "unknown", "SW/타사업 분담 또는 혼합 금액 미확정"
            if re.search(r"대기업.{0,15}참여.{0,15}예외(?:인정|승인)|예외(?:인정|승인)사업", all_text):
                return "unknown", "별도 SW 참여제한 예외 확인 필요"
            below = prices["sw_below_20eok"]
            if below is None:
                return "unknown", "SW VAT포함 20억원 경계 금액 충돌/부재"
            maintenance = bool(re.search(r"유지보수|유지관리|유지및지원", actual_text))
            if not below and maintenance and re.search(r"장기계속|장기계약|연차별|차년도|다년도", all_text):
                return "unknown", "장기계속 SW 유지보수는 연평균금액 확인 필요"
            return ("competitive" if below else "general"), "SW 지침3조 VAT포함 사업금액 20억원 미만 여부=" + str(below)
        if row["세부품명"] == "컴퓨터서버":
            # The CSV explicitly limits this row to x86. ARM is stated in a
            # processor specification, not inferred from a model/brand name.
            specs = [d["text"] for d in _docs(rec) if d.get("type") == "규격서"]
            arm = any(re.search(r"(?:processor|cpu|프로세서)\s*[:：][^\n]{0,80}\barm\b", t, re.I) for t in specs)
            x86 = any(re.search(r"\bx86\b", t, re.I) for t in specs)
            if arm and not x86:
                return "general", "실제 규격의 Processor=ARM으로 CSV x86 조건 미충족"
            return "unknown", "CSV 서버 CPU 수/기본주파수 조건을 완전히 확인하지 못함"
        if row["세부품명"] == "간장":
            return "unknown", "혼합간장 한정조건 및 전체 구매품목 구성 미확정"
        if row["세부품명"] == "시설물경비서비스":
            if re.search(r"기계경비|특수경비", actual_text):
                return "general", "CSV 제외 대상 기계경비/특수경비가 실제 과업"
            if re.search(r"자회사", all_text) and "수의" in str((rec.get("meta") or {}).get("계약방법")):
                return "unknown", "경비 자회사 수의 예외 확인 필요"
            if re.search(r"시설물경비서비스|시설경비|시설물경비|청사경비|일반경비", actual_text):
                return "competitive", "실제 일반 시설경비이며 CSV 제외유형 미관측"
            return "unknown", "경비업 세부유형 불명확"
        return "unknown", "기타 CSV 특이사항은 자동판정 범위 밖: " + condition

    def classify(self, rec) -> dict:
        result = {"product_kind": "unknown", "product_basis": "", "evidence": [], "candidates": []}
        if not self.available:
            result["product_basis"] = "제공 경쟁제품CSV 미확인"
            return result
        meta = rec.get("meta", {}) or {}
        if "공사" in str(meta.get("업무구분", "")):
            result["product_basis"] = "공사는 자동분류 범위 밖"
            return result
        fields = _actual_fields(rec)
        primary_fields = [x for x in fields if x["type"] == "공고문"]
        anchors = primary_fields or fields
        actual = _norm("\n".join(x["text"] for x in anchors))
        all_text = _norm("\n".join(d["text"] for d in _docs(rec)))
        raw_primary = "\n".join(d["text"] for d in _docs(rec) if d.get("type") == "공고문")
        prices = _prices(rec)
        if re.search(r"등\s*\d{2,}\s*종", "\n".join(x["text"] for x in fields)):
            result["product_basis"] = "다품종 구매의 전체 제품구성과 조건을 자동확정하지 않음"
            return result
        # Explicit statutory exclusion must identify THIS purchase and a
        # procurement-exception provision, not just a generic law quotation.
        exclusion = re.search(r"[^\n]{0,180}(?:시행령|제7조)[^\n]{0,180}(?:제외하고|제외하여)[^\n]{0,60}일반물품[^\n]{0,80}", raw_primary)
        if exclusion and "제7조" in exclusion.group() and re.search(r"특별한사정|특정한기술|제1항제4호", _norm(exclusion.group())):
            result.update(product_kind="general", product_basis="공고가 제공 판로영7조 특별사유에 따른 경쟁제품 적용제외를 명시", evidence=[exclusion.group()[:350]])
            return result
        matched = {}
        direct_codes = set()
        for anchor in fields:
            text = anchor["text"]
            norm = _norm(text)
            # A ten-digit phone/date in a business title is not a product code.
            if re.search(r"(?:세부품명|물품분류)(?:번호|코드)?", _norm(text)):
                direct_codes.update(_CODE.findall(text))
            for code, row in self.rows.items():
                name = _norm(row["세부품명"])
                # Short names such as '표/요/간장' are not unbounded substrings.
                name_match = len(name) >= 4 and name in norm
                if code in direct_codes or name_match:
                    matched.setdefault(code, {"row": row, "source": anchor, "match": "실제 품명/코드 필드"})
        # Metadata product codes require independent actual-task support; they
        # cannot transfer a certificate's product into an unrelated research job.
        meta_codes = set(_CODE.findall(str(meta.get("세부품명번호목록") or "")))
        for code in meta_codes:
            if code not in self.rows:
                continue
            row = self.rows[code]
            name = _norm(row["세부품명"])
            source = next(({"text": line, "doc_id": d.get("doc_id", "")}
                           for d in _docs(rec) if d.get("type") == "규격서"
                           for line in d["text"].splitlines()
                           if len(name) >= 4 and name in _norm(line)), None)
            if source:
                matched.setdefault(code, {"row": row, "source": source, "match": "구매메타와 규격서 품명 일치"})
        # Narrow supplied-product paraphrases. These describe actual task-title
        # content; registration/certificate prose is not part of 'actual'.
        aliases = []
        if _ACTION.search(actual):
            if re.search(r"박람회|전시회", actual):
                aliases.append(("8014198801", "실제 박람회/전시회 기획·운영"))
            elif re.search(r"축제", actual):
                aliases.append(("9015189001", "실제 축제 기획·대행"))
            elif re.search(r"페스티벌|문화제", actual):
                # A branded festival can denote a trade exhibition or a local
                # festival. When their supplied monetary conditions differ,
                # preserve ambiguity rather than choosing a favorable code.
                aliases.extend([("9015189001", "페스티벌/문화제는 축제 여부 모호"),
                                ("8014199001", "페스티벌/문화제는 기타행사 여부 모호")])
            elif re.search(r"국제(?:행사|포럼|회의|대회)", actual):
                aliases.append(("8014198901", "실제 국제행사/포럼 기획·대행"))
            elif re.search(r"공연|버스킹|기념식|행사", actual):
                aliases.append(("8014199001", "실제 공연/행사 기획·대행"))
        if _SW_OBJECT.search(actual) and _SW_ACTION.search(actual) and "소프트웨어" in all_text and not re.search(r"장비구매|물품구매|컴퓨터구매", actual):
            code = "8111189901" if re.search(r"유지보수|유지관리|운영", actual) else "8111159901"
            aliases.append((code, "실제 정보시스템/SW 구축 또는 유지보수 과업"))
        if re.search(r"시설물경비|시설경비|청사경비|일반경비", actual):
            aliases.append(("9212159901", "실제 시설 경비 과업"))
        for code, reason in aliases:
            if code in self.rows:
                matched.setdefault(code, {"row": self.rows[code], "source": anchors[0] if anchors else {"text": "", "doc_id": ""}, "match": reason})
        # ARM server exclusion has strong actual processor evidence even when
        # a redacted title omits the public metadata's server noun.
        if meta_codes == {"4321150102"} and "4321150102" in self.rows:
            row = self.rows["4321150102"]
            kind, why = self._condition(row, rec, actual, all_text, prices)
            if kind == "general":
                literal = [m.group()[:350] for d in _docs(rec) if d.get("type") == "규격서"
                           for m in re.finditer(r"[^\n]*(?:processor|cpu|프로세서)\s*[:：][^\n]{0,80}\barm\b[^\n]*", d["text"], re.I)]
                result.update(product_kind=kind, product_basis=why, evidence=literal[:2])
                return result
        if not matched:
            # Closed-list membership is useful only for actual purchase fields,
            # never a metadata/certificate-only code or failed fuzzy search.
            if direct_codes and not (direct_codes & self.rows.keys()):
                result.update(product_kind="general", product_basis="실제 구매 필드의 모든10자리 품목코드가 제공CSV에 없음", evidence=[x["text"][:350] for x in anchors[:2]])
            else:
                result["product_basis"] = "실제 구매대상과 제공 품목의 확실한 연결 없음"
            return result
        decisions = []
        for code, match in matched.items():
            kind, why = self._condition(match["row"], rec, actual, all_text, prices)
            record = {"code": code, "name": match["row"]["세부품명"], "special_condition": match["row"]["특이사항"],
                      "match": match["match"], "decision": kind, "reason": why, "source": match["source"]["text"][:350]}
            decisions.append(record)
        result["candidates"] = decisions
        outcomes = {d["decision"] for d in decisions}
        unmatched_meta = meta_codes - self.rows.keys()
        if len(outcomes) == 1 and "unknown" not in outcomes and not (direct_codes - self.rows.keys()) and not unmatched_meta:
            result["product_kind"] = next(iter(outcomes))
            result["product_basis"] = "; ".join(d["name"] + ": " + d["reason"] for d in decisions)[:150]
            result["evidence"] = [d["source"] for d in decisions[:3]]
        else:
            result["product_basis"] = "복수 실제품목/특이사항의 분류가 상충하거나 미확정"
        return result
