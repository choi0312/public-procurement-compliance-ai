"""Absence across fully observed alternative qualification branches.

An OR can make a present condition optional. It cannot introduce a condition
which is absent from every fully observed branch. Unresolved references,
truncation, positive candidates, and ambiguous mentions still require abstention.
"""
from copy import deepcopy
from pps_qualification_facts import _mask_laws, _norm_map, _SCOPE


def refine_disjunction_absence(rec, literal):
    out = deepcopy(literal)
    diag = out['diagnostics']
    blockers = diag.get('blockers', [])
    if not blockers or any(b != '자격 전체의 선택적 OR 조건' for b in blockers):
        return out
    sections = diag.get('sections', [])
    if not diag.get('primary_notice_observed') or not sections or not all(s['closed'] for s in sections):
        return out
    # Broken table/OCR syntax can defeat the possession-verb parser. A bare
    # source mention still prevents an absence proof even without a candidate.
    texts = []
    for section in sections:
        doc = next((d for d in rec['docs'] if d['doc_id'] == section['doc_id']), None)
        if doc is None: return out
        texts.append(_norm_map(doc['text'][section['start']:section['end']])[0])
    scope_mentioned = any(_SCOPE.search(_mask_laws(text)) for text in texts)
    direct_mentioned = any('직접생산' in text for text in texts)
    if (out['direct_production_required'] == 'unknown'
            and not direct_mentioned and not diag.get('direct_candidates') and not diag.get('direct_unresolved')):
        out['direct_production_required'] = 'no'
        out['direct_production_e'] = None
    if (out['enterprise_scope'] == 'unknown'
            and not scope_mentioned and not diag.get('scope_candidates') and not diag.get('scope_unresolved')):
        out['enterprise_scope'] = 'unrestricted'
        out['enterprise_e'] = None
    return out
