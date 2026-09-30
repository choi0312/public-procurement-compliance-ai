"""Necessary price conditions remain necessary when another fact is unknown.

These exclusions implement the supplied item table, not a fitted threshold.
They never infer an affirmative violation or a procurement exception.
"""
from copy import deepcopy
from decimal import Decimal


def apply_invariants(obj,rec):
    out=deepcopy(obj);changes=[];facts=obj.get('facts') or {}
    scope=str((rec.get('meta') or {}).get('업무구분') or '')
    if '공사' in scope or not any(v in scope for v in ('물품','용역')):return out,changes
    if facts.get('product_kind')!='general':return out,changes
    price=facts.get('price')
    if type(price) is not int or price<=0:return out,changes
    # Require the model's amount to agree on ALL applicable bands with every
    # available explicit primary estimate and metadata estimate. A conflict
    # is left for semantic review, never resolved by majority or a gold label.
    from pps_rules import effective_price
    parsed=effective_price(rec)
    if not parsed['reliable']:return out,changes
    values=[Decimal(v['amount']) for v in parsed['body_estimates']]
    if parsed['meta_amount'] is not None:values.append(Decimal(parsed['meta_amount']))
    band=lambda p:0 if p<100_000_000 else 1 if p<230_000_000 else 2
    if not values or any(band(v)!=band(price) for v in values):return out,changes
    excluded=({14,15,16} if band(price)==0 else {14,17,18} if band(price)==1 else {15,16,17,18})
    for n in sorted(excluded):
        if out['v'][n-1] or out['e'][n-1]:
            changes.append({'item':f'v{n}','before':out['v'][n-1],'after':0,'rule':'provided item necessary price band excludes this condition'})
            out['v'][n-1]=0;out['e'][n-1]=None
    return out,changes
