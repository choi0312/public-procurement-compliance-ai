"""Exact current-notice qualification clauses and arithmetic, never a label."""
from decimal import Decimal
import re

from pps_rules import qualification_evidence,_qualification_sections,_BODY_MONEY,_meta_price

RESOURCE=re.compile(r"시설|수리\s*센터|인력|기술자|종업원|직원|점포|차량|장비|대학|연구\s*기관|연구소|산학|공공기관|국공립")
REQUIRE=re.compile(r"보유|소유|있는\s*(?:자|업체|기관)|한정|한함|에\s*한|참가|갖춘|갖추|대상")
FUTURE=re.compile(r"투입\s*예정|배치\s*예정|계약\s*후|계약체결\s*후|낙찰\s*후|수행\s*시")
UNITS={'':1,'백':100,'천':1000,'만':10000,'백만':1000000,'천만':10000000,'억':100000000}


def qualification_focus(rec):
    """Find existing eligibility clauses without classifying their legality."""
    results=[];seen=set()
    def add(doc_id,quote,kind):
        if not quote or len(quote)>500 or (doc_id,quote) in seen:return
        doc=next((d for d in rec['docs'] if d['doc_id']==doc_id and quote in d['text']),None)
        if doc is None:return
        seen.add((doc_id,quote));results.append({'doc_id':doc_id,'text':quote,'start':doc['text'].find(quote),'kind':kind})
    for found in qualification_evidence(rec):add(found['doc_id'],found['evidence'],'past_performance_eligibility')
    for doc in rec['docs']:
        if doc['type']!='공고문':continue
        for begin,end in _qualification_sections(doc['text']):
            section=doc['text'][begin:end]
            lines=list(re.finditer(r'[^\n]+',section))
            for line in lines:
                value=line.group().strip()
                if RESOURCE.search(value) and REQUIRE.search(value) and not FUTURE.search(value):add(doc['doc_id'],value,'participant_or_resource_eligibility')
    return results[:12]


def comparison_facts(rec,clause):
    """Literal KRW minimum versus both current meta amounts, without a verdict."""
    if clause['kind']!='past_performance_eligibility':return []
    raw=clause['text'];meta=rec.get('meta') or {};out=[]
    if re.search(r'달러|USD|EUR|유로|연평균|연간|월간|단가',raw,re.I):return []
    for match in _BODY_MONEY.finditer(raw):
        if re.search(r'[억만천]\s*$',raw[max(0,match.start()-10):match.start()]):continue
        if not re.match(r'\s*(?:\([^)]{0,30}\)\s*)?이\s*상',raw[match.end():]):continue
        amount=Decimal(match['num'].replace(',',''))*UNITS[re.sub(r'\s+','',match['unit'] or '')]
        if amount<=0 or amount>Decimal('1000000000000000'):continue
        current={key:_meta_price(meta.get(key)) for key in ('입찰추정가격','배정예산금액')}
        detail={'required_past_performance_krw':str(amount),'source_literal':match.group(),'comparisons':{}}
        for key,value in current.items():
            if value is not None:detail['comparisons'][key]={'current_krw':str(value),'required_greater':amount>value,'ratio':format(amount/value,'.4f')}
        out.append(detail)
    return out


def append_focus(rec,spans,max_chars=2200):
    """Append bounded exact source spans when needed, and return cited hints."""
    spans=[dict(s) for s in spans];facts=[];used=0
    for clause in qualification_focus(rec):
        if used+len(clause['text'])>max_chars:continue
        same=next((s for s in spans if s['doc_id']==clause['doc_id'] and clause['text'] in s['text']),None)
        if same is None:
            doc=next(d for d in rec['docs'] if d['doc_id']==clause['doc_id'])
            same={'sid':f's{len(spans)+1:03d}','doc_id':clause['doc_id'],'type':doc['type'],'start':clause['start'],'end':clause['start']+len(clause['text']),'text':clause['text']}
            spans.append(same)
        facts.append({'sid':same['sid'],'clause_type':clause['kind'],'exact_clause':clause['text'],'arithmetic':comparison_facts(rec,clause)})
        used+=len(clause['text'])
    return spans,facts
