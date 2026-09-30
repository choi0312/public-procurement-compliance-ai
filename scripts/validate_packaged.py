#!/usr/bin/env python3
"""Run the actual submitted entry point against a public-only runtime mount."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--workload",type=Path,required=True)
    p.add_argument("--data-dir",type=Path,required=True)
    p.add_argument("--model-dir",type=Path,default=Path("/workspace/pps_model"))
    p.add_argument("--output-root",type=Path,required=True)
    p.add_argument("--cpu-count",type=int,default=7)
    p.add_argument("--fresh-kernel-cache",action="store_true")
    a=p.parse_args();root=a.output_root.resolve()
    if root.exists():raise ValueError("Use a new validation output directory")
    root.mkdir(parents=True);package=root/"package";package.mkdir()
    with zipfile.ZipFile(a.archive) as z:
        for entry in z.infolist():
            target=(package/entry.filename).resolve()
            if not target.is_relative_to(package):raise ValueError("Unsafe archive path")
        z.extractall(package)
    if not (package/"script.py").is_file():raise ValueError("Missing root script.py")
    data=root/"mounted_data";data.mkdir()
    for source in a.data_dir.resolve().iterdir():
        if source.name!="test.jsonl.gz":(data/source.name).symlink_to(source,target_is_directory=source.is_dir())
    (data/"test.jsonl.gz").symlink_to(a.workload.resolve())
    allowed=sorted(os.sched_getaffinity(0))
    if len(allowed)<a.cpu_count:raise ValueError("Insufficient allowed CPUs")
    os.sched_setaffinity(0,set(allowed[:a.cpu_count]))
    env=dict(os.environ,PPS_DATA_DIR=str(data),PPS_OUTPUT_DIR=str(root/"output"),
             PPS_MODEL_DIR=str(a.model_dir.resolve()),HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
    cache_settings={}
    if a.fresh_kernel_cache:
        cache_settings={"VLLM_CACHE_ROOT":str(root/"kernel_cache/vllm"),
                        "TORCHINDUCTOR_CACHE_DIR":str(root/"kernel_cache/inductor"),
                        "TRITON_CACHE_DIR":str(root/"kernel_cache/triton")}
        assert all(not Path(value).exists() for value in cache_settings.values())
        env.update(cache_settings)
    started=time.monotonic();observed_memory=0;observations=0
    memory_candidates=[Path("/sys/fs/cgroup/memory.current"),Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")]
    memory_path=next((p for p in memory_candidates if p.exists()),memory_candidates[0])
    with (root/"execution.log").open("w") as log:
        process=subprocess.Popen(["python3","script.py","--save-details"],cwd=package,env=env,
                                 stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        while process.poll() is None:
            try:
                observed_memory=max(observed_memory,int(memory_path.read_text()))
                observations+=1
            except (OSError,ValueError):pass
            time.sleep(1)
    report={"exit_code":process.returncode,"total_wall_seconds":time.monotonic()-started,
            "archive_sha256":hashlib.sha256(a.archive.read_bytes()).hexdigest(),
            "workload_sha256":hashlib.sha256(a.workload.read_bytes()).hexdigest(),
            "cpu_affinity":sorted(os.sched_getaffinity(0)),"network_mode":"HF and Transformers offline",
            "max_observed_container_memory_bytes":observed_memory,"memory_observations":observations,
            "memory_source":str(memory_path),
            "memory_limit_note":"Read-only container cgroup; observed usage, not an enforced official 60GiB cap",
            "fresh_kernel_cache":bool(a.fresh_kernel_cache),"kernel_cache_settings":cache_settings,
            "cache_scope":"Fresh vLLM/Inductor/Triton directories when requested; OS model-file page cache is not forcibly evicted",
            "entrypoint":"python3 script.py --save-details; input/output/model paths supplied only via PPS environment"}
    (root/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)
    if process.returncode:raise SystemExit(process.returncode)


if __name__=="__main__":main()
