"""Explicit current-notice priority-procurement exemptions, supplied law 2-3.

Only absence items v16/v18 are negated. This does not excuse excessive
affirmative qualifications, declare a product general, or use other notices.
"""
import re


def priority_exemption(rec):
    primary = [d for d in rec.get('docs',[]) if d.get('type')=='공고문']
    if any(re.search(r'우선조달(?:계약)?.{0,25}예외.{0,12}(?:해당하지않|해당되지않|적용하지않|적용되지않|해당하지아니|해당되지아니|적용하지아니|적용되지아니|대상이아니|대상이아닙|적용안|가아니|가아닙)',
                     re.sub(r'\s+','',d.get('text',''))) for d in primary):
        return None
    for doc in rec.get('docs', []):
        if doc.get('type') != '공고문':
            continue
        text = doc.get('text', '')
        for match in re.finditer(r'우선\s*조달\s*(?:계약)?', text):
            start = max(0, match.start()-180)
            end = min(len(text), match.end()+150)
            clause = text[start:end]
            compact = re.sub(r'\s+', '', clause)
            after = re.sub(r'\s+', '', text[match.end():end])
            if not re.search(r'중소기업|판로지원|공공구매제도|제2조의3',compact):
                continue
            hit = re.match(r'(?:에대한)?[「｢(]?예외[」｣)]?(?:가|에|를)?(?:해당합니다|적용합니다|(?:해당하는|적용되는)(?:용역|입찰|사업|계약)(?:입니다|임(?=[.。;,]|$)|이며)|대상입니다)',after)
            if not hit:
                continue
            if re.match(r'''[.。"'“”‘’「」『』｢｣)]*(?:라는|라고|란)''',after[hit.end():]):
                continue
            # A contingent or quoted future rule does not affirm this tender's
            # exemption; an actual exception statement must be unambiguous.
            nearby = re.sub(r'\s+','',text[max(0,match.start()-80):match.start()])
            if re.search(r'예를들|예시|경우|이라면|일때|때에만|가능하면|적용될수',nearby):
                continue
            return {'doc_id':doc.get('doc_id'),'start':start,'end':end,'text':clause}
    return None


def apply_priority_exemption(rec,row):
    if not priority_exemption(rec):
        return row
    out = dict(row)
    for n in (16,18):
        out[f'v{n}'] = 0
        out[f'e{n}'] = ''
    return out
