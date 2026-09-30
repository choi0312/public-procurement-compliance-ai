#!/usr/bin/env python3
"""Build an allowlisted deterministic code ZIP, then audit its actual contents."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from test_submission_contract import audit_archive


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",default=str(ROOT/"deliverables/submission.zip"));args=parser.parse_args()
    package=ROOT/"submission";out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    files=[p for p in package.glob("*.py")]+[package/"requirements.txt",package/"SOURCES.md"]
    config=json.loads((package/"model/config.json").read_text())
    if config.get("specialist_pipeline"):
        passes=[{**config,**value} for value in config.get("specialist_passes",{}).values()]
    elif config.get("two_pass"):
        passes=[{**config,**config.get(key,{})} for key in ("reasoned_pass","facts_pass")]
    else:passes=[config]
    assets={"config.json","item_guidance.json"}
    if any(c.get("fewshot_k",0) for c in passes):assets.update(("dev_examples.json.gz","examples_provenance.json"))
    if any(c.get("item_example_items") for c in passes):assets.update(("item_examples.json.gz","item_examples_provenance.json"))
    files += [package/"model"/name for name in sorted(assets)]
    records=[]
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(files):
            if p.is_symlink():raise ValueError("Symlinks are not allowed")
            data=p.read_bytes();name=str(p.relative_to(package))
            info=zipfile.ZipInfo(name,date_time=(2026,9,6,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,data)
            records.append({"name":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    errors=audit_archive(out)
    if errors:raise RuntimeError(errors)
    report={"archive":out.name,"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"compressed_bytes":out.stat().st_size,"uncompressed_bytes":sum(r["bytes"] for r in records),"members":records,"archive_audit":"PASS","leaderboard_score":None}
    out.with_suffix(".manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ["archive","sha256","compressed_bytes","archive_audit"]}))


if __name__=="__main__":main()
