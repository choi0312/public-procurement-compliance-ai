#!/usr/bin/env python3
"""Strict ID-aligned, positive-class macro-F1 for 24 competition labels."""
import argparse
import csv
import json
from pathlib import Path


def read_rows(path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    if len({r["id"] for r in rows})!=len(rows):raise ValueError("Duplicate IDs")
    return {r["id"]:r for r in rows}


def evaluate(truth_path,prediction_path,allow_subset=False):
    truth=read_rows(truth_path);pred=read_rows(prediction_path)
    if not pred or not set(pred).issubset(truth):raise ValueError("Unknown or empty prediction ID set")
    if not allow_subset and set(pred)!=set(truth):raise ValueError("Incomplete prediction ID set")
    per_item={};errors={}
    for i in range(1,25):
        key=f"v{i}";tp=fp=fn=tn=0;wrong=[]
        for rid in pred:
            y,p=truth[rid][key],pred[rid][key]
            if y not in ("0","1") or p not in ("0","1"):raise ValueError("Non-binary value")
            tp+=y==p=="1";tn+=y==p=="0";fp+=y=="0" and p=="1";fn+=y=="1" and p=="0"
            if y!=p:wrong.append({"id":rid,"truth":int(y),"prediction":int(p)})
        f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
        per_item[key]={"tp":tp,"fp":fp,"fn":fn,"tn":tn,"f1":f1,"positives":tp+fn}
        errors[key]=wrong
    return {"macro_f1":sum(v["f1"] for v in per_item.values())/24,"records":len(pred),"complete_dev":set(pred)==set(truth),"per_item":per_item,"errors":errors}


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("truth");p.add_argument("prediction");p.add_argument("--output");p.add_argument("--allow-subset",action="store_true");a=p.parse_args()
    result=evaluate(a.truth,a.prediction,a.allow_subset)
    if a.output:Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ["macro_f1","records","complete_dev"]}))
