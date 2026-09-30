"""Record-local comparisons of the four supplied v24 metadata axes.

Only explicit primary-notice statements can contradict metadata. Missing
statements are unknown, not matching evidence. A negative requires all four
axes affirmatively matched. No labels, notice IDs, learned state or network.
"""
from copy import deepcopy
from decimal import Decimal
import re

from pps_region import extract_region_qualifications, PROVINCE_RE
from pps_regional_rules import _OPEN_REGION, _ALTERNATIVE_CONDITIONS
from pps_rules import _meta_price


AXES=("budget","contract_method","region","industry")
PROVENANCE=["항목표.json v24", "https://dacon.io/competitions/official/236754/talkboard/417272",
            "https://dacon.io/competitions/official/236754/talkboard/417321"]
_MONEY=re.compile(
    r"(?P<label>추\s*정\s*가\s*격|사\s*업\s*예\s*산|소\s*요\s*예\s*산|배\s*정\s*예\s*산(?:\s*금\s*액)?|예\s*산\s*금\s*액|예\s*산\s*액)"
    r"(?P<before>\s*\([^\n)]{0,35}\))?\s*[:：]?\s*(?:금\s*)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit>억|천\s*만|백\s*만|만|천|백)?\s*원"
)
_METHODS={"일반경쟁":"일반경쟁","제한경쟁":"제한경쟁","지명경쟁":"지명경쟁","수의계약":"수의계약"}
_METHOD_WORD=re.compile(r"일반\s*경쟁|제한\s*경쟁|지명\s*경쟁|수의\s*(?:계약|\(총액\)|\(단가\))")
_METHOD_LABEL=re.compile(r"(?:입\s*찰|계\s*약)\s*(?:및\s*계\s*약\s*)?방\s*법\s*[:：]")
_CURRENT_METHOD=re.compile(r"(?:본|이)\s*(?:입찰|계약)은|^\s*(?:[가-하][.)]\s*)?(?:총액입찰|총액계약|제한경쟁|일반경쟁)")
_FUTURE=re.compile(r"유찰|재공고|재입찰|전환|할\s*수|경우에는|경우에\s*한")
_QUAL_HEAD=re.compile(r"(?:입찰(?:\s*\(응모\))?|공모[·ㆍ‧/및\s]*입찰|견적(?:제출)?)\s*참가\s*자격")
_NEXT_SECTION=re.compile(r"^\s*\d{1,2}[.)]\s*(?:낙찰|제출|접수|입찰보증|계약|제안서|평가|기타|청렴)")
_BULLET=re.compile(r"^\s*(?:[가-하][.)]|[①-⑳○●□■•ㅇ✓※❍]|\d{1,2}[.)]|-)\s*")
_CODE=re.compile(r"(?:업종\s*(?:코드|번호)\s*[:：]?\s*(?P<explicit>\d{4})(?!\d)|\(\s*(?P<plain>\d{4})\s*\))")
_REGISTER=re.compile(r"(?:입찰\s*참가\s*자격.{0,25}등록|등록.{0,20}(?:필한|마친|완료|업체|자)|신고.{0,15}(?:필한|마친|업체|자)|허가.{0,15}(?:받은|득한)|면허.{0,15}(?:소지|보유))",re.S)
_NONMANDATORY=re.compile(r"가점|배점|평가점수|우대|권장|등록하지\s*않아도|등록\s*여부와\s*무관")
_REGISTRATION_WAIVER=re.compile(r"등록\s*하지\s*않아도|등록\s*여부와\s*무관|등록.{0,70}(?:필요(?:가)?\s*없|필요하지\s*않|요하지\s*않|의무(?:가)?\s*아니)|미등록.{0,35}참가(?:가)?\s*가능",re.S)
_OR=re.compile(r"또\s*는|혹\s*은|어느\s*하나")
_AND=re.compile(r"(?:과|와|및)\s|모두|동시")


def _compact(value):return re.sub(r"\s+","",str(value or ""))


def _docs(rec):
    return [d for d in rec.get("docs",[]) if isinstance(d,dict) and d.get("type")=="공고문" and isinstance(d.get("text"),str)]


def _axis(status="unknown",evidence="",doc_id="",reason="",observed=None):
    return {"status":status,"evidence":evidence,"doc_id":doc_id,"reason":reason,"observed":observed}


def _quote(text,start,end):
    left=text.rfind("\n",0,start)+1
    if end-left>500:left=start
    right=text.find("\n",end)
    if right<0:right=len(text)
    return text[left:min(right,left+500)].strip()


def _valid(rec,evidence,doc_id):
    return bool(evidence) and len(evidence)<=500 and not evidence.startswith(("=","+","@")) and any(
        d.get("doc_id")==doc_id and evidence in d["text"] for d in _docs(rec))


def _budget(rec):
    meta=rec.get("meta") or {}
    targets={"estimate":_meta_price(meta.get("입찰추정가격")),"budget":_meta_price(meta.get("배정예산금액"))}
    values={"estimate":[],"budget":[]}
    units={"":1,"백":100,"천":1000,"만":10000,"백만":1000000,"천만":10000000,"억":100000000}
    for doc in _docs(rec):
        text=doc["text"]
        # A stated '추정가격' may describe a unit-price basis in a unit bid,
        # while the metadata contains the aggregate procurement estimate.
        unit_bid=bool(re.search(r"단가\s*(?:계약|입찰|견적)|기초\s*단가",text[:5000]))
        for match in _MONEY.finditer(text):
            prefix=text[max(text.rfind("\n",0,match.start())+1,match.start()-60):match.start()]
            if re.search(r"총사업|총\s*$|연간|연차|차년도|차분|장기계속|예시|예\s*[):：]|가정|산식|평가|실적|고시",prefix):continue
            if re.search(r"(?:연간|월간|월별|월액|연차별|[1-9]\s*차년도|단가)\s*[)\]]?\s*\n\s*$",text[max(0,match.start()-100):match.start()]):continue
            tail=text[match.end():match.end()+50]
            if re.match(r"\s*(?:미만|이상|이하|초과|부터|[~∼]|[일인]\s*(?:경우|때))",tail):continue
            period_context=prefix+(match["before"] or "")+text[match.end():match.end()+200].split("\n",1)[0]
            if re.search(r"월간|월액|월별|일간|일액|일별|연간|연차별|[1-9]\s*차년도|[1-9]\s*차분|분기별|학기별|인당|개당|회당|단가|/\s*(?:월|일|인|개|회)\b",period_context):continue
            amount=Decimal(match["num"].replace(",",""))*units[_compact(match["unit"])]
            if amount<=0:continue
            annotation=(match["before"] or "")+tail.split("\n",1)[0]
            included=bool(re.search(r"(?:부가(?:가치)?세|VAT).{0,30}포함",annotation,re.I))
            excluded=bool(re.search(r"(?:부가(?:가치)?세|VAT).{0,30}(?:제외|별도|미포함)",annotation,re.I))
            if included and excluded:continue
            label=_compact(match["label"])
            field="estimate" if label=="추정가격" else "budget"
            if field=="estimate" and (included or unit_bid):continue
            if field=="budget" and (not included or excluded):continue
            ev=_quote(text,match.start(),match.end())
            values[field].append((amount,ev,doc.get("doc_id","")))
    matched=set();observed={}
    for field,entries in values.items():
        if targets[field] is None or not entries:continue
        distinct={amount for amount,_,_ in entries}
        if len(distinct)!=1:continue
        amount,ev,doc=entries[0]
        observed[field]={"body":str(amount),"meta":str(targets[field])}
        # KRW rounding differences are not a procurement-budget discrepancy.
        if abs(amount-targets[field])>Decimal("2"):
            return _axis("contradiction",ev,doc,"same-field explicit primary-notice amount differs",observed)
        matched.add(field)
    if matched=={"estimate","budget"}:
        amount,ev,doc=values["budget"][0]
        return _axis("match",ev,doc,"both explicit comparable financial fields match",observed)
    return _axis(observed=observed)


def _contract_method(rec):
    target=_compact((rec.get("meta") or {}).get("계약방법"))
    if target not in _METHODS:return _axis()
    observations=[]
    for doc in _docs(rec):
        text=doc["text"]
        for line in re.finditer(r"[^\n]+",text):
            value=line.group()
            explicit=bool(_METHOD_LABEL.search(value) or _CURRENT_METHOD.search(value))
            quotation_title=(line.start()<650 and bool(re.search(r"수의\s*(?:계약)?\s*(?:견적.{0,20})?안내\s*공고",value)))
            if not (explicit or quotation_title) or _FUTURE.search(value):continue
            found={_compact(m.group()) for m in _METHOD_WORD.finditer(value)}
            found={"수의계약" if s.startswith("수의") else s for s in found}
            if quotation_title:found.add("수의계약")
            # A small quotation can itself limit bidders. Its use of
            # '제한경쟁' does not turn the quotation into competitive procurement.
            if re.search(r"수의\s*견적|소액\s*수의",value):found={"수의계약"}
            if len(found)==1 and len(value.strip())<=500:observations.append((found.pop(),value.strip(),doc.get("doc_id","")))
    if not observations or len({v[0] for v in observations})!=1:return _axis()
    method,ev,doc=observations[0]
    return _axis("match" if method==target else "contradiction",ev,doc,
                 "competitive/negotiated procurement method; award method such as negotiation is separate",{"body":method,"meta":target})


def _region(rec):
    meta=rec.get("meta") or {};flag=_compact(meta.get("지역제한여부")).upper()
    if flag not in {"Y","N"}:return _axis()
    primary={**rec,"docs":_docs(rec)}
    if any(_ALTERNATIVE_CONDITIONS.search(_compact(d["text"])) for d in _docs(rec)):return _axis()
    clauses=[c for c in extract_region_qualifications(primary) if c["office_location_explicit"]
             and not _OPEN_REGION.search(_compact(c["text"]))]
    if clauses and flag=="N":
        c=clauses[0]
        return _axis("contradiction",c["text"],c["doc_id"],"metadata explicitly says no region restriction but primary bidder-office qualification exists",{"meta_flag":flag})
    openings=[]
    for d in _docs(rec):
        for m in re.finditer(r"지역\s*제한\s*[:：]\s*(?:없음|해당\s*없음)",d["text"]):
            openings.append((_quote(d["text"],m.start(),m.end()),d.get("doc_id","")))
    if openings and not clauses:
        ev,doc=openings[0]
        return _axis("match" if flag=="N" else "contradiction",ev,doc,"explicit current region restriction field",{"meta_flag":flag})
    if flag=="Y" and len(clauses)==1:
        c=clauses[0];regions=c["regions"]
        if regions and all(r["unit"]=="province" and r.get("province") for r in regions):
            body={r["province"] for r in regions}
            raw=str(meta.get("제한지역코드목록") or "")
            supplied=set(PROVINCE_RE.findall(raw))
            residual=PROVINCE_RE.sub("",raw)
            if supplied and re.fullmatch(r"[\s,·ㆍ/\[\]]*",residual):
                return _axis("match" if body==supplied else "contradiction",c["text"],c["doc_id"],
                             "explicit full-province eligibility sets",{"body":sorted(body),"meta":sorted(supplied)})
    return _axis()


def _minimal_dnf(groups):
    unique=set(frozenset(g) for g in groups)
    return frozenset(g for g in unique if not any(other<g for other in unique))


def _metadata_industry(raw):
    if not isinstance(raw,str) or not raw.strip():return None
    groups=list(re.finditer(r"\[([^\]]+)\]",raw))
    if not groups:return None
    if raw[:groups[0].start()].strip() or raw[groups[-1].end():].strip():return None
    if any(not re.fullmatch(r"\s*(?:업종)?\s*또는\s*",raw[a.end():b.start()]) for a,b in zip(groups,groups[1:])):return None
    alternatives=[]
    for group in groups:
        matches=list(re.finditer(r"\((\d{4})\)",group[1]));codes=[m[1] for m in matches]
        if not codes:return None
        between=[group[1][a.end():b.start()] for a,b in zip(matches,matches[1:])]
        if any(not _AND.search(s) or _OR.search(s) for s in between):return None
        alternatives.append(codes)
    return _minimal_dnf(alternatives)


def _qualification_blocks(text):
    lines=list(re.finditer(r"[^\n]+",text));sections=[]
    for i,line in enumerate(lines):
        value=line.group().strip()
        if len(value)>90 or not _QUAL_HEAD.search(value) or re.search(r"평가|증명|등록규정",value):continue
        end=min(len(text),line.end()+6500)
        for following in lines[i+1:]:
            if following.start()>=end:break
            if _NEXT_SECTION.match(following.group()):end=following.start();break
        sections.append((line.end(),end))
    for begin,end in sections:
        section=text[begin:end]
        if re.search(r"(?:아래|다음).{0,80}(?:중|에서)\s*(?:어느\s*)?하나",section[:350],re.S):continue
        entries=list(re.finditer(r"[^\n]+",section))
        if not entries:continue
        start=entries[0].start()
        for line in entries[1:]:
            if _BULLET.match(line.group()):
                raw=section[start:line.start()].strip()
                yield raw
                start=line.start()
        raw=section[start:entries[-1].end()].strip()
        yield raw


def _industry(rec):
    meta=rec.get("meta") or {};flag=_compact(meta.get("업종제한여부")).upper()
    if flag not in {"Y","N"}:return _axis()
    meta_dnf=_metadata_industry(meta.get("면허업종제한목록"))
    clauses=[];ambiguous=False
    for doc in _docs(rec):
        blocks=list(_qualification_blocks(doc["text"]))
        # A following exception can waive an earlier mandatory code. Do not
        # compare a fragment of this more complex registration expression.
        if any(_REGISTRATION_WAIVER.search(b) for b in blocks):
            ambiguous=True;continue
        # A parent bullet such as '등록한 업체 (① 또는 ②)' governs child
        # code bullets. Treating each child as mandatory would change OR to AND.
        if any(_OR.search(b) and not _CODE.search(b) and (_REGISTER.search(b) or re.search(r"[①-⑳]\s*또\s*는\s*[①-⑳]|[가-하]\s*목\s*또\s*는\s*[가-하]\s*목",b)) for b in blocks):
            ambiguous=True;continue
        for raw in blocks:
            matches=list(_CODE.finditer(raw))
            if _NONMANDATORY.search(raw):continue
            if not matches:
                if _REGISTER.search(raw):ambiguous=True
                continue
            if len(raw)>500 or not _REGISTER.search(raw):
                ambiguous=True;continue
            codes=[m["explicit"] or m["plain"] for m in matches]
            if any(1900<=int(code)<=2099 for code in codes) and not re.search(r"업종\s*(?:코드|번호)",raw):
                ambiguous=True;continue
            # Uncoded alternatives ('registered X OR equipment qualification')
            # and shared code prefixes require a richer parse; never truncate.
            between=" ".join(raw[a.end():b.start()] for a,b in zip(matches,matches[1:]))
            if len(_OR.findall(raw))!=len(_OR.findall(between)):
                ambiguous=True;continue
            if len(codes)==1:dnf=_minimal_dnf([codes])
            else:
                has_or=bool(_OR.search(between));has_and=bool(_AND.search(between))
                if has_or and not has_and:dnf=_minimal_dnf([[code] for code in codes])
                elif has_and and not has_or:dnf=_minimal_dnf([codes])
                else:ambiguous=True;continue
            key=(doc.get("doc_id",""),raw,dnf)
            if key not in clauses:clauses.append(key)
    if clauses and flag=="N":
        doc,ev,dnf=clauses[0]
        return _axis("contradiction",ev,doc,"metadata explicitly says no industry restriction but mandatory coded registration exists",{"body_dnf":[sorted(g) for g in dnf],"meta_flag":flag})
    if clauses and flag=="Y" and meta_dnf is not None:
        for doc,ev,body in clauses:
            # An explicit metadata alternative permits a code combination that
            # does not satisfy this mandatory body clause: direct contradiction.
            if any(not any(required<=allowed for required in body) for allowed in meta_dnf):
                return _axis("contradiction",ev,doc,"metadata industry alternatives admit a combination excluded by the primary mandatory clause",
                             {"body_dnf":[sorted(g) for g in body],"meta_dnf":[sorted(g) for g in meta_dnf]})
        if not ambiguous:
            combined=_minimal_dnf([[]])
            for _,_,body in clauses:combined=_minimal_dnf([a|b for a in combined for b in body])
            if combined==meta_dnf:
                doc,ev,_=clauses[0]
                return _axis("match",ev,doc,"explicit coded AND/OR eligibility expressions match")
    if not clauses and not ambiguous:
        for doc in _docs(rec):
            for m in re.finditer(r"업종\s*제한\s*[:：]\s*(?:없음|해당\s*없음)",doc["text"]):
                ev=_quote(doc["text"],m.start(),m.end())
                return _axis("match" if flag=="N" else "contradiction",ev,doc.get("doc_id",""),"explicit current industry restriction field")
    return _axis()


def metadata_assessment(rec):
    if not _docs(rec):return {axis:_axis() for axis in AXES}
    return {"budget":_budget(rec),"contract_method":_contract_method(rec),"region":_region(rec),"industry":_industry(rec)}


def metadata_override(rec):
    axes=metadata_assessment(rec)
    for axis in ("budget","contract_method","industry","region"):
        value=axes[axis]
        if value["status"]=="contradiction" and _valid(rec,value["evidence"],value["doc_id"]):
            return {"v24":1,"e24":value["evidence"],"axis":axis,"axes":axes,"provenance":PROVENANCE}
    if all(axes[axis]["status"]=="match" for axis in AXES):
        return {"v24":0,"e24":"","axis":"all_four_match","axes":axes,"provenance":PROVENANCE}
    return None


def apply_metadata_rules(rec,row):
    out=deepcopy(row);correction=metadata_override(rec)
    if correction is not None:out.update(v24=correction["v24"],e24=correction["e24"])
    return out
