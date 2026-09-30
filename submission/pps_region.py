"""High-precision, record-local extraction of geographic bidder qualifications.

Returns source facts, not v5-v8/v24 judgments. The metadata region flag is never
used to suppress a condition explicitly written in a document. An empty result
does not prove that no geographic restriction exists.
"""
from __future__ import annotations

import re

# Spellings observed in the supplied dev anonymization fields (광역=...). These
# are a text recognition lexicon, not externally downloaded geographic data.
PROVINCES = (
    "강원특별자치도", "경기도", "경상남도", "경상북도", "광주광역시",
    "대구광역시", "대전광역시", "부산광역시", "서울특별시", "세종특별자치시",
    "울산광역시", "인천광역시", "전라남도", "전북특별자치도", "제주특별자치도",
    "충청남도", "충청북도",
)
PROVINCE_RE = re.compile("|".join(sorted(PROVINCES, key=len, reverse=True)))
PLACEHOLDER_RE = re.compile(r"\[지역:([^\]|]+)(?:\|[^\]]*)?\]")
AUTHORITY_TERRITORY_RE = re.compile(r"\[(?:수요기관|기관)\((기초자치단체|광역자치단체)\)(?:\|[^\]]*)?\](?=\s*(?:내|관내|관할))")
OFFICE_RE = re.compile(r"본\s*점|본\s*사|주\s*된\s*(?:영업소|사무소)|주\s*사무소|주\s*사\s*무\s*소|사업자\s*등록\s*상\s*소재지|법인\s*등기부\s*상\s*소재지")
LOCATED_COMPANY_RE = re.compile(r"(?:소재|위치)(?:하[는고]|한|하고\s*있는|해\s*있는|하여야\s*하는)?\s*(?:업체|기업|사업자)")
REGIONAL_COMPANY_RE = re.compile(r"(?:지역|관내)\s*(?:업체|기업|사업자)")
SECTION_HEADING_RE = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[가-하][.)]|[○●□■])\s*([^\n]{1,55})$")
QUALIFICATION_TITLE_RE = re.compile(r"(?:입찰\s*)?참가\s*자격|신청\s*자격|입찰\s*참여\s*자격")
OTHER_SECTION_RE = re.compile(r"^(?:입찰에\s*부치는|사업\s*(?:개요|내용|장소)|납품|제출|접수|공고\s*기간|제안서\s*(?:접수|제출)|계약\s*방법|평가\s*방법|세부\s*추진|기타)")
LOCATION_RE = re.compile(r"소재|위치|두고|둔|두어|있어야|있는\s*(?:업체|기업|자)|관할\s*구역|안에\s*있|내에\s*있")
QUALIFIER_RE = re.compile(r"업체|기업|사업자|입찰|참가|자격|있어야|하여야|해야|둔\s*자|둔\s*업체")
UNRELATED_RE = re.compile(r"납품\s*(?:장소|위치|주소|지)|제출\s*(?:장소|주소|처)|접수\s*(?:장소|주소|처)|발주\s*기관\s*(?:주소|소재)|수요\s*기관\s*(?:주소|소재)|수행\s*장소|사업\s*장소|현장\s*위치")
UNRESTRICTED_RE = re.compile(r"지역\s*제한\s*(?:없|을\s*두지|하지\s*않)|소재지[와에]\s*관계없이|본점[의\s]*지역[과에]\s*관계없이|전국\s*(?:모든\s*)?업체")
FORM_FIELD_RE = re.compile(r"(?:본점|본사|주\s*사무소|영업소)\s*소재지\s*\n\s*(?:상\s*호|업체명|성\s*명|사업자등록번호|주민등록번호)")
SUBREGION_LIST_RE = re.compile(r"\s+([가-힣]{2,8})\s*[,·]\s*([가-힣]{2,8}?)(?=\s*(?:에|내에|관내|지역))")
NEXT_BULLET_RE = re.compile(r"\n\s*(?:[가-하]\s*[.)]|[①-⑳]|[○●□■※•‣❍◦]|-\s|\d{1,2}[.)])\s*")


def _bounds(text, start, end, max_chars=500):
    # Most extracted HWP line wraps are preserved; follow the current bullet to
    # its natural boundary instead of treating every newline as a new clause.
    left = text.rfind("\n", 0, start) + 1
    if start - left > 250:
        left = max(0, start - 180)
    right = min(len(text), left + max_chars)
    double = text.find("\n\n", end, right)
    if double >= 0:
        right = min(right, double)
    bullet = NEXT_BULLET_RE.search(text, end, right)
    if bullet:
        right = min(right, bullet.start())
    # Korean sentence endings avoid cutting dates, decimals or article numbers.
    sentence = re.search(r"(?:합니다|됩니다|합니다만|함|한다|있다|없다|이어야\s*합니다|하여야\s*한다)\.[ \t]*(?:\n|$)", text[end:right])
    if sentence:
        right = end + sentence.end()
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right-1].isspace():
        right -= 1
    return left, right


def _regions(clause, offset):
    mentions = []
    placeholder_ranges = []
    for match in PLACEHOLDER_RE.finditer(clause):
        attributes = dict(re.findall(r"([^|=\[\]]+)=([^|\]]+)", match.group()))
        unit = {"기초": "basic", "광역": "province"}.get(attributes.get("단위"), "unknown")
        mentions.append({"text": match.group(), "start": offset+match.start(), "end": offset+match.end(),
                         "kind": "placeholder", "token_id": match.group(1), "unit": unit,
                         "province": attributes.get("광역"), "role": "restriction"})
        placeholder_ranges.append((match.start(), match.end()))
    for match in AUTHORITY_TERRITORY_RE.finditer(clause):
        # The name stays unresolved: this only recognizes an explicit reference
        # to the authority's territory, not its address or an external mapping.
        region_attr = re.search(r"\|지역=([^|\]]+)", match.group())
        mentions.append({"text": match.group(), "start": offset+match.start(), "end": offset+match.end(),
                         "kind": "authority_territory", "token_id": region_attr.group(1) if region_attr else None,
                         "unit": "basic" if match.group(1) == "기초자치단체" else "province",
                         "province": None, "role": "restriction"})
        placeholder_ranges.append((match.start(), match.end()))
    for match in PROVINCE_RE.finditer(clause):
        if any(a <= match.start() < b for a,b in placeholder_ranges):
            continue
        role = "restriction"
        subregions = SUBREGION_LIST_RE.match(clause, match.end())
        if subregions:
            # Names without 시/군/구 suffixes cannot safely determine the level.
            # Preserve the two explicit nested areas, rather than incorrectly
            # collapsing '경기도 여주, 양평에' into all of 경기도.
            role = "parent_context"
            for group in (1, 2):
                name = subregions.group(group)
                mentions.append({"text": name, "start": offset+subregions.start(group), "end": offset+subregions.end(group),
                                 "kind": "literal_subregion", "token_id": None,
                                 "unit": "basic" if re.search(r"[시군구]$", name) else "unknown",
                                 "province": match.group(), "role": "restriction"})
        for mention in mentions:
            if mention["unit"] != "basic" or mention["province"] != match.group():
                continue
            local_start = mention["start"] - offset
            if match.end() <= local_start and re.fullmatch(r"\s*(?:의|소재)?\s*", clause[match.end():local_start]):
                role = "parent_context"
        mentions.append({"text": match.group(), "start": offset+match.start(), "end": offset+match.end(),
                         "kind": "literal_province", "token_id": None, "unit": "province",
                         "province": match.group(), "role": role})
    mentions.sort(key=lambda m: m["start"])
    effective = []
    seen = set()
    for mention in mentions:
        if mention["role"] != "restriction":
            continue
        identity = mention["text"] if mention["kind"] == "literal_subregion" else (mention["token_id"] or mention["province"] or mention["text"])
        key = (mention["unit"], identity)
        if key not in seen:
            seen.add(key)
            effective.append(mention)
    return mentions, effective


def _in_qualification_section(text, position):
    """Allow terse 'X 지역 업체' only within an explicit nearby qualification list."""
    in_section = False
    for heading in SECTION_HEADING_RE.finditer(text, max(0, position-2000), position):
        title = heading.group(1).strip()
        if QUALIFICATION_TITLE_RE.search(title):
            in_section = True
        elif OTHER_SECTION_RE.search(title):
            in_section = False
    return in_section


def extract_region_qualifications(rec, max_clauses=12):
    """Return actual location qualification clauses with codepoint offsets.

    ``region_unit`` is basic/province/multiple/unknown. Parent province text
    directly preceding a basic placeholder is not a second eligible territory.
    Raw placeholders and their source positions remain available in mentions.
    No statutory thresholds, exception judgments or violation labels are added.
    """
    if max_clauses <= 0:
        return []
    found = []
    for doc_index, doc in enumerate(rec.get("docs") or []):
        text = doc.get("text")
        if not isinstance(text, str):
            continue
        matches = list(OFFICE_RE.finditer(text)) + list(LOCATED_COMPANY_RE.finditer(text))
        matches += [m for m in REGIONAL_COMPANY_RE.finditer(text) if _in_qualification_section(text, m.start())]
        candidates = sorted({(m.start(), m.end()) for m in matches})
        seen = set()
        for anchor_start, anchor_end in candidates:
            start, end = _bounds(text, anchor_start, anchor_end)
            clause = text[start:end]
            if not clause or (start,end) in seen:
                continue
            seen.add((start,end))
            terse_regional_qualification = (REGIONAL_COMPANY_RE.search(clause) is not None
                                            and _in_qualification_section(text, anchor_start))
            if not (LOCATION_RE.search(clause) or terse_regional_qualification) or not QUALIFIER_RE.search(clause):
                continue
            if UNRESTRICTED_RE.search(clause):
                continue
            if FORM_FIELD_RE.search(clause):
                continue
            if UNRELATED_RE.search(clause):
                # A location explicitly tied to delivery/receipt/performance is
                # not a bidder-address requirement, even if a bank has a 본점.
                continue
            mentions, effective = _regions(clause, start)
            if not effective:
                continue
            has_office = OFFICE_RE.search(clause) is not None
            if not has_office and re.search(r"실적|수행한|납품한|발주한|개최한", clause):
                continue
            units = {m["unit"] for m in effective}
            scope = "multiple" if len(effective)>1 else next(iter(units))
            found.append({"doc_id": str(doc.get("doc_id", "")), "type": str(doc.get("type", "기타")),
                          "start": start, "end": end, "text": clause,
                          "region_unit": scope, "multiple": len(effective)>1,
                          "regions": effective, "mentions": mentions,
                          "office_location_explicit": has_office,
                          "meta_region_flag": (rec.get("meta") or {}).get("지역제한여부"),
                          "classification": "textual_bidder_location_requirement"})
            if len(found) >= max_clauses:
                return found
    return found
