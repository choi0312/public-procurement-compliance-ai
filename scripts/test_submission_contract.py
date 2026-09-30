#!/usr/bin/env python3
"""Independent DACON submission contracts. stdlib only; no GPU/API calls.

Run: python scripts/test_submission_contract.py
Optional archive audit: PPS_AUDIT_ZIP=/absolute/submit.zip python scripts/test_submission_contract.py
"""
from __future__ import annotations

import copy
import csv
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "submission"
COLUMNS = ["id"] + [f"v{i}" for i in range(1, 25)] + [f"e{i}" for i in range(1, 25)]
ABSENCE = {10, 11, 16, 18, 20}
SENSITIVE = re.compile(rb"(?:rpa_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
WEIGHT_SUFFIXES = {".safetensors", ".gguf", ".pt", ".pth", ".ckpt", ".bin", ".onnx", ".h5"}
_ARCHIVE = os.environ.get("PPS_AUDIT_ZIP")


def csv_contract_errors(path, records):
    errors = []
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("UTF-8 BOM")
    text = raw.decode("utf-8")
    if text != unicodedata.normalize("NFC", text):
        errors.append("non-NFC output")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or rows[0] != COLUMNS:
        return errors + ["header mismatch"]
    actual = rows[1:]
    by_id = {record["id"]: record for record in records}
    ids = [row[0] for row in actual if row]
    if len(ids) != len(records) or len(set(ids)) != len(ids) or set(ids) != set(by_id):
        errors.append("ID/row contract")
    for row in actual:
        if len(row) != 49:
            errors.append("row width")
            continue
        if any(value not in {"0", "1"} for value in row[1:25]):
            errors.append("nonbinary label")
        rec = by_id.get(row[0])
        for item in range(1, 25):
            ev = row[24 + item]
            if len(ev) > 500 or ev.startswith(("=", "+", "@")):
                errors.append("evidence cell")
            if ev and (row[item] != "1" or item in ABSENCE):
                errors.append("forbidden evidence")
            if ev and rec and not any(ev in unicodedata.normalize("NFC", d["text"]) for d in rec["docs"]):
                errors.append("evidence not in one document")
    return errors


def audit_archive(path):
    """Fail on secrets/weights/raw inputs, invalid ZIP paths and oversize archives."""
    errors = []
    if Path(path).stat().st_size > 2_000_000_000:
        errors.append("compressed > 2GB conservative bound")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        normalized = [unicodedata.normalize("NFC", entry.filename) for entry in entries]
        if len(set(normalized)) != len(normalized):
            errors.append("duplicate normalized archive names")
        if "script.py" not in normalized:
            errors.append("script.py missing at ZIP root")
        if sum(entry.file_size for entry in entries) > 8_000_000_000:
            errors.append("expanded > 8GB conservative bound")
        for entry in entries:
            name = entry.filename
            path_obj = Path(name)
            if path_obj.is_absolute() or ".." in path_obj.parts or "\\" in name:
                errors.append("unsafe archive member")
            if stat.S_ISLNK(entry.external_attr >> 16):
                errors.append("symlink archive member")
            if any(part.startswith(".env") or part in {".git", ".ssh", "__pycache__"} for part in path_obj.parts):
                errors.append("private/cache member")
            if path_obj.name.startswith(("id_rsa", "id_ed25519")) or path_obj.suffix.lower() in {".pem", ".key", ".pub"}:
                errors.append("credential member")
            if path_obj.suffix.lower() in WEIGHT_SUFFIXES:
                errors.append("model weight member")
            if path_obj.parts and path_obj.parts[0] in {"data", "artifacts"}:
                errors.append("raw/runtime input member")
            if name.endswith((".jsonl", ".jsonl.gz")) or path_obj.name in {"train_unlabeled.jsonl.gz", "dev_labels.csv", "open.zip"}:
                errors.append("raw dataset member")
            if not entry.is_dir() and entry.file_size <= 50_000_000 and SENSITIVE.search(archive.read(entry)):
                errors.append("secret signature")
    return errors


def pipeline_module():
    sys.path.insert(0, str(PACKAGE))
    spec = importlib.util.spec_from_file_location("pps_submission_under_test", PACKAGE / "script.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_record():
    return {
        "id": "contract-synthetic-unique",
        "meta": {},
        "docs": [
            {"doc_id": "notice", "type": "공고문", "text": "공고 본문입니다.\n인용에 쉼표, 따옴표 \"예시\"와 줄바꿈이 있습니다."},
            {"doc_id": "attachment", "type": "규격서", "text": "별도 문서의 첫 문장입니다."},
        ],
    }


def zero_object():
    return {"v": [0] * 24, "e": [None] * 24}


class PipelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = pipeline_module()

    def test_strict_binary_json(self):
        self.assertEqual(self.module.parse_result(json.dumps(zero_object())), zero_object())
        for bad in (True, "1", 0.1, 2, None):
            obj = zero_object()
            obj["v"][0] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.module.parse_result(json.dumps(obj))
        for text in ("", "{}", '{"v":[],"e":[]}', '{"v":null,"e":null}', "not JSON"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.module.parse_result(text)

    def test_reasoned_keyed_items_normalize_without_position_shift(self):
        obj={f"v{i}":{"reason":"basis", "v":int(i in {2,12,24}),"e":None} for i in range(1,25)}
        parsed=self.module.parse_result(json.dumps(dict(reversed(list(obj.items())))))
        self.assertEqual([i+1 for i,v in enumerate(parsed["v"]) if v],[2,12,24])
        obj["v2"]["v"]="1"
        with self.assertRaises(ValueError):self.module.parse_result(json.dumps(obj))

    def test_native_final_json_excludes_thought_examples(self):
        final=zero_object()
        final["v"][23]=1
        text='<|channel>thought\nExample: '+json.dumps(zero_object())+'\n<channel|>\n'+json.dumps(final)
        self.assertEqual(self.module.parse_result(self.module.extract_gemma_answer(text)),final)
        self.assertEqual(self.module.extract_gemma_answer(json.dumps(final)+'<turn|>'),json.dumps(final))
        for invalid in (
            '<|channel>thought\n'+json.dumps(zero_object()),
            '<|channel>thought<channel|>',
            '<|channel>thought<channel|>'+json.dumps(final)+'<|channel>thought',
            'Unmarked reasoning '+json.dumps(zero_object()),
            json.dumps(final)+' unrelated trailing prose',
        ):
            with self.subTest(invalid=invalid[:40]), self.assertRaises(ValueError):
                self.module.extract_gemma_answer(invalid)

    def test_native_engine_can_switch_schema_and_template_without_reloading(self):
        captured={}
        class FakeTokenizer:
            def apply_chat_template(self,messages,**kwargs):
                captured["template"]=kwargs
                return list(range(12 if kwargs["enable_thinking"] else 10))
        class FakeLLM:
            def __init__(self,**kwargs):captured["engine"]=kwargs
            def get_tokenizer(self):return FakeTokenizer()
            def chat(self,batch,**kwargs):
                captured["chat"]=kwargs
                output=type("Output",(),{"text":'<|channel>thought\n'+json.dumps({"irrelevant":"example"})+'<channel|>'+json.dumps(zero_object()),"finish_reason":"stop","token_ids":[1,2,3]})()
                return [type("Request",(),{"outputs":[output]})() for _ in batch]
        fake_vllm=type(sys)("vllm")
        fake_vllm.LLM=FakeLLM
        fake_vllm.SamplingParams=lambda **kwargs:kwargs
        fake_sp=type(sys)("vllm.sampling_params")
        fake_sp.StructuredOutputsParams=lambda **kwargs:kwargs
        fake_config=type(sys)("vllm.config")
        fake_config.ReasoningConfig=lambda **kwargs:kwargs
        config=dict(self.module.default_config(),native_thinking=True,thinking_token_budget=1024,max_output_tokens=2048,output_format="compact")
        with tempfile.TemporaryDirectory() as local_model, mock.patch.dict(sys.modules,{"vllm":fake_vllm,"vllm.sampling_params":fake_sp,"vllm.config":fake_config}):
            runner=self.module.Runner(local_model,config)
            messages=[{"role":"user","content":"synthetic notice"}]
            self.assertEqual(runner.count(messages),12)
            result=runner.generate([messages])
            self.assertEqual(self.module.parse_result(result[0]["text"]),zero_object())
            self.assertEqual(result[0]["generated_tokens"],3)
            self.assertEqual(captured["engine"]["reasoning_parser"],"gemma4")
            self.assertFalse(captured["engine"]["structured_outputs_config"]["enable_in_reasoning"])
            self.assertEqual(captured["chat"]["sampling_params"]["thinking_token_budget"],1024)
            self.assertFalse(captured["chat"]["sampling_params"]["skip_special_tokens"])
            self.assertTrue(captured["chat"]["chat_template_kwargs"]["enable_thinking"])
            runner.configure(dict(config,native_thinking=False,output_format="reasoned",max_output_tokens=4096))
            self.assertEqual(runner.count(messages),10)
            runner.generate([messages])
            self.assertFalse(captured["chat"]["chat_template_kwargs"]["enable_thinking"])
            self.assertNotIn("thinking_token_budget",captured["chat"]["sampling_params"])
            self.assertEqual(runner.structured["json"],self.module.REASONED_SCHEMA)

    def test_native_mode_cannot_enable_on_incompatible_engine(self):
        runner=self.module.Runner.__new__(self.module.Runner)
        runner.mock=False
        runner._native_capable=False
        with self.assertRaises(ValueError):runner.configure({"native_thinking":True})

    def test_exact_evidence_and_forbidden_cells(self):
        rec = sample_record()
        quote = rec["docs"][0]["text"]
        spans = [{"sid": "s001", "doc_id": "notice", "text": quote}]
        obj = zero_object()
        obj["v"][0] = 1
        obj["e"][0] = "s001"
        obj["e"][1] = "s001"  # Negative item must drop a provided quote.
        for item in ABSENCE:
            obj["v"][item - 1] = 1
            obj["e"][item - 1] = "s001"
        row = self.module.resolve_row(rec, obj, spans)
        self.assertEqual(row["e1"], quote)
        self.assertEqual(row["e2"], "")
        for item in ABSENCE:
            self.assertEqual(row[f"e{item}"], "")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "submission.csv"
            self.module.io.write_csv([row], str(path))
            self.assertEqual(csv_contract_errors(path, [rec]), [])

    def test_no_cross_document_or_fabricated_evidence(self):
        rec = sample_record()
        for value in (
            rec["docs"][0]["text"][-12:] + "\n" + rec["docs"][1]["text"][:12],
            "문서에 없는 허구의 근거",
            "A" * 501,
            "=SUM(A1:A2)",
        ):
            obj = zero_object()
            obj["v"][0] = 1
            obj["e"][0] = value
            with self.subTest(value=value[:30]):
                self.assertEqual(self.module.resolve_row(rec, obj, [])["e1"], "")

    def test_span_id_case_and_padding_resolve_to_same_source(self):
        rec = sample_record()
        spans = [{"sid": "s001", "doc_id": "notice", "text": rec["docs"][0]["text"]}]
        quote = "공고 본문입니다."
        for sid in ("s001", "S001", "S1", "s1"):
            obj = zero_object()
            obj["v"][0] = 1
            obj["e"][0] = sid + "|" + quote
            with self.subTest(sid=sid):
                self.assertEqual(self.module.resolve_row(rec, obj, spans)["e1"], quote)

    def test_model_initialization_uses_supplied_path(self):
        captured = {}
        class FakeLLM:
            def __init__(self, **kwargs):
                captured.update(kwargs)
            def get_tokenizer(self):
                return object()
        fake_vllm = type(sys)("vllm")
        fake_vllm.LLM = FakeLLM
        fake_vllm.SamplingParams = lambda **kwargs: kwargs
        fake_sp = type(sys)("vllm.sampling_params")
        fake_sp.StructuredOutputsParams = lambda **kwargs: kwargs
        fake_config = type(sys)("vllm.config")
        fake_config.ReasoningConfig = lambda **kwargs: kwargs
        with tempfile.TemporaryDirectory() as local_model:
            with mock.patch.dict(sys.modules, {"vllm": fake_vllm, "vllm.sampling_params": fake_sp, "vllm.config": fake_config}):
                self.module.Runner(local_model, self.module.default_config())
            self.assertEqual(captured["model"], local_model)
            self.assertEqual(captured["tokenizer"], local_model)
        self.assertEqual(captured["tensor_parallel_size"], 1)
        self.assertFalse(captured["trust_remote_code"])

    def test_missing_local_model_fails_before_any_hub_download(self):
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(FileNotFoundError):
                self.module.Runner(str(Path(parent)/"missing-model"), self.module.default_config())

    def test_failure_propagates_without_zero_submission(self):
        class FailingRunner:
            mock = False
            load_seconds = 0
            def count(self, messages):
                return 100
            def generate(self, *args, **kwargs):
                raise RuntimeError("synthetic unavailable model")
        pipeline = self.module.Pipeline.__new__(self.module.Pipeline)
        pipeline.runner = FailingRunner()
        pipeline.config = self.module.default_config()
        pipeline.prepare = lambda rec: {"messages": [{"role": "user", "content": rec["docs"][0]["text"]}], "spans": [], "prompt_tokens": 20, "prompt_sha256": "test"}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                pipeline.predict([sample_record()], temp)
            self.assertFalse((Path(temp) / "submission.csv").exists())

    def test_invalid_response_cannot_be_counted_normal(self):
        class InvalidRunner:
            mock = False
            load_seconds = 0
            def count(self, messages):
                return 100
            def generate(self, batch, **kwargs):
                return [{"text": "", "finish_reason": "stop", "generated_tokens": 0} for _ in batch]
        pipeline = self.module.Pipeline.__new__(self.module.Pipeline)
        pipeline.runner = InvalidRunner()
        pipeline.config = self.module.default_config()
        pipeline.prepare = lambda rec: {"messages": [{"role": "user", "content": rec["docs"][0]["text"]}], "spans": [], "prompt_tokens": 20, "prompt_sha256": "test"}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "bounded recovery"):
                pipeline.predict([sample_record()], temp)
            self.assertFalse((Path(temp) / "submission.csv").exists())

    def test_cli_environment_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data = base / "isolated_data"
            output = base / "isolated_output"
            shutil.copytree(ROOT / "data/official/data", data, ignore=shutil.ignore_patterns("test.jsonl.gz"))
            with gzip.open(ROOT / "data/official/data/test.jsonl.gz", "rt", encoding="utf-8") as f:
                rec = json.loads(next(f))
            rec["id"] = "contract-env-path-unique"
            with gzip.open(data / "test.jsonl.gz", "wt", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            env = dict(os.environ, PPS_DATA_DIR=str(data), PPS_OUTPUT_DIR=str(output), PPS_MODEL_DIR=str(base / "unused_fixed_model"), PPS_EMBED_DIR=str(base / "unused_embed"))
            process = subprocess.run([sys.executable, str(PACKAGE / "script.py"), "--mock"], cwd=base, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr[-2500:])
            self.assertEqual(csv_contract_errors(output / "submission.csv", [rec]), [])
            report = json.loads((output / "run_report.json").read_text())
            self.assertEqual(report["mode"], "mock")
            self.assertEqual(report["normal_model_responses"], 0)
            self.assertFalse((base / "output").exists())


class ArchiveContracts(unittest.TestCase):
    def test_archive_scanner_rejects_weights_and_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("script.py", "pass\n")
                archive.writestr("model/weights.safetensors", b"fake")
                archive.writestr(".env", "API_KEY=placeholder\n")
                archive.writestr("../escape.py", "pass")
            errors = audit_archive(path)
            self.assertIn("model weight member", errors)
            self.assertIn("private/cache member", errors)
            self.assertIn("unsafe archive member", errors)

    def test_submission_source_package(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for source in PACKAGE.rglob("*"):
                    if source.is_file() and "__pycache__" not in source.parts:
                        archive.write(source, str(source.relative_to(PACKAGE)))
            self.assertEqual(audit_archive(path), [])

    @unittest.skipUnless(_ARCHIVE, "PPS_AUDIT_ZIP not provided; source package is still audited")
    def test_delivery_archive(self):
        self.assertEqual(audit_archive(_ARCHIVE), [])


if __name__ == "__main__":
    unittest.main()
