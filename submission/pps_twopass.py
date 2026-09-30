"""Optional two-pass adapter using the existing frozen-model Pipeline.

The reasoned response supplies the baseline. Known facts from the same notice
can change only v10-v18 through the existing provided-rule truth table. No
gold labels, other notices' predictions, or batch statistics enter a decision.
"""
from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import time

import pps_io as io
import pps_logic
import pps_rules
from script import Pipeline, parse_result, resolve_row


FACT_ITEMS = tuple(range(10, 19))
POST_OPTIONS = ("statutory_rules", "joint_rules", "regional_rules", "qualification_facts", "procedure_rules", "product_facts", "facts_baseline", "metadata_rules", "briefing_dates", "software_rules", "fact_invariants", "qualification_disjunction_absence", "explicit_priority_exemption")
ENGINE_OPTIONS = (
    "max_model_len",
    "quantization", "gpu_memory_utilization", "max_num_batched_tokens",
    "max_num_seqs", "kv_cache_dtype", "calculate_kv_scales",
    "kv_cache_dtype_skip_layers",
    "deterministic_scheduling", "batch_invariant", "enforce_eager",
)


def _unique_index(values, name):
    result = {}
    for value in values:
        identifier = value.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError(f"Missing or duplicate {name} notice ID")
        result[identifier] = value
    return result


def _base_row(rec, row):
    if set(row) != set(io.COLUMNS) or row.get("id") != rec["id"]:
        raise ValueError("Reasoned row must have the exact 49 columns and matching notice ID")
    out = {"id": rec["id"]}
    for n in range(1, 25):
        value = row[f"v{n}"]
        if type(value) is int and value in (0, 1):
            label = value
        elif isinstance(value, str) and value in ("0", "1"):
            label = int(value)
        else:
            raise ValueError("Reasoned row contains an invalid label")
        evidence = row[f"e{n}"]
        if not isinstance(evidence, str):
            raise ValueError("Reasoned row contains non-string evidence")
        if evidence and (len(evidence) > 500 or not any(evidence in d["text"] for d in rec["docs"])):
            raise ValueError("Reasoned evidence is not a bounded original-source quote")
        if evidence and (not label or n in (10, 11, 16, 18, 20)):
            raise ValueError("Reasoned row has evidence in a mandatory blank cell")
        out[f"v{n}"] = label
        out[f"e{n}"] = evidence
    return out


def _check_spans(rec, spans):
    seen = set()
    for span in spans:
        sid = span.get("sid")
        if not isinstance(sid, str) or sid in seen:
            raise ValueError("Missing or duplicate facts span ID")
        seen.add(sid)
        start, end = span.get("start"), span.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("Invalid facts span offsets")
        if not any(d["doc_id"] == span["doc_id"] and d["text"][start:end] == span["text"]
                   and end <= len(d["text"]) for d in rec["docs"]):
            raise ValueError("Facts span does not belong to this notice's original source")


def _postprocess(rec, row, config):
    out = dict(row)
    if config.get("statutory_rules"):
        out = pps_rules.apply_statutory_rules(rec, out)
    if config.get("joint_rules"):
        correction = pps_rules.v21_override(rec)
        if correction is not None:
            out.update(v21=correction["v21"], e21=correction["e21"])
    if config.get("regional_rules"):
        from pps_regional_rules import apply_regional_rules
        out = apply_regional_rules(rec, out)
    if config.get("procedure_rules"):
        from pps_procedure_rules import apply_procedure_rules
        out = apply_procedure_rules(rec, out)
    if config.get("metadata_rules"):
        from pps_metadata_rules import apply_metadata_rules
        out = apply_metadata_rules(rec, out)
    if config.get("briefing_dates"):
        from pps_briefing_dates import apply_briefing_dates
        out = apply_briefing_dates(rec, out)
    if config.get("software_rules"):
        from pps_software_rules import apply_software_rules
        out = apply_software_rules(rec, out)
    if config.get('explicit_priority_exemption'):
        from pps_priority import apply_priority_exemption
        out = apply_priority_exemption(rec,out)
    changes = []
    for n in range(1, 25):
        if row[f"v{n}"] != out[f"v{n}"] or row[f"e{n}"] != out[f"e{n}"]:
            changes.append({"item": f"v{n}", "before": row[f"v{n}"], "after": out[f"v{n}"],
                            "evidence_changed": row[f"e{n}"] != out[f"e{n}"],
                            "rule": "provided_statutory_postprocessing"})
    return out, changes


def fuse_record(rec, reasoned_row, facts_object, facts_spans, post_config=None, product_classifier=None):
    """Fuse one resolved baseline row and the same notice's parsed facts.

    The facts response's own v/e predictions are intentionally ignored. Its
    evidence span IDs are resolved against its own preparation, never against
    the reasoned pass's different source windows. Returns (row, audit_changes).
    """
    baseline = _base_row(rec, reasoned_row)
    _check_spans(rec, facts_spans)
    delegated_changes=[]
    if (post_config or {}).get("facts_baseline"):
        factual_baseline=resolve_row(rec,facts_object,facts_spans)
        for n in FACT_ITEMS:
            label,evidence=f"v{n}",f"e{n}"
            if baseline[label]!=factual_baseline[label] or baseline[evidence]!=factual_baseline[evidence]:
                delegated_changes.append({"item":label,"before":baseline[label],"after":factual_baseline[label],"rule":"facts pass supplies delegated product item"})
            baseline[label],baseline[evidence]=factual_baseline[label],factual_baseline[evidence]
    candidate = {
        "v": [baseline[f"v{n}"] for n in range(1, 25)],
        "e": [baseline[f"e{n}"] or None for n in range(1, 25)],
    }
    if "facts" in facts_object:
        candidate["facts"] = deepcopy(facts_object["facts"])
        if (post_config or {}).get("product_facts"):
            if product_classifier is None:raise ValueError("Product correction requires the supplied CSV classifier")
            product=product_classifier.classify(rec)
            if product["product_kind"] != "unknown":
                candidate["facts"]["product_kind"]=product["product_kind"]
                candidate["facts"]["product_basis"]=product["product_basis"][:150]
        if (post_config or {}).get("qualification_facts"):
            from pps_qualification_facts import extract_qualification_facts
            literal = extract_qualification_facts(rec)
            if (post_config or {}).get('qualification_disjunction_absence'):
                from pps_qualification_logic import refine_disjunction_absence
                literal = refine_disjunction_absence(rec, literal)
            for field, evidence in (("direct_production_required", "direct_production_e"),
                                    ("enterprise_scope", "enterprise_e")):
                if literal[field] != "unknown":
                    candidate["facts"][field] = literal[field]
                    candidate["facts"][evidence] = literal[evidence]

    def valid_fact_evidence(value):
        if not value:
            return False
        probe = {"v": [1]+[0]*23, "e": [value]+[None]*23}
        return bool(resolve_row(rec, probe, facts_spans)["e1"])

    combined, decisions = pps_logic.apply_facts(candidate, rec, valid_fact_evidence)
    if (post_config or {}).get('fact_invariants'):
        from pps_fact_invariants import apply_invariants
        combined, invariant_changes=apply_invariants(combined,rec)
        decisions+=invariant_changes
    resolved = resolve_row(rec, combined, facts_spans)
    out = dict(baseline)
    changes = []
    decision_rules = {c["item"]: c["rule"] for c in decisions}
    for n in FACT_ITEMS:
        label, evidence = f"v{n}", f"e{n}"
        if (combined["v"][n-1], combined["e"][n-1]) == (candidate["v"][n-1], candidate["e"][n-1]):
            # An already-resolved baseline quote may itself literally be
            # 's001'. Unknown/unmodified facts must never reinterpret that
            # original text as a span ID from the other pass.
            continue
        out[label], out[evidence] = resolved[label], resolved[evidence]
        if baseline[label] != out[label] or baseline[evidence] != out[evidence]:
            changes.append({"item": label, "before": baseline[label], "after": out[label],
                            "evidence_changed": baseline[evidence] != out[evidence],
                            "rule": decision_rules.get(label, "same-label fact evidence refresh")})
    out, post_changes = _postprocess(rec, out, post_config or {})
    return out, delegated_changes + changes + post_changes


def combine_replay(records, reasoned_rows, facts_details, facts_prepare, post_config=None, product_classifier=None):
    """Offline replay with strict one-to-one notice joins, without labels.

    ``facts_prepare(rec)`` must reproduce the facts pass's preparation and
    return a dict containing spans and (when recorded) prompt_sha256. The
    original captured preparation can also be supplied by a lookup callback.
    Mismatched, missing, duplicate, or extra IDs fail instead of being reused.
    """
    records = list(records)
    source = _unique_index(records, "input")
    baseline = _unique_index(reasoned_rows, "reasoned")
    details = _unique_index(facts_details, "facts")
    if set(source) != set(baseline) or set(source) != set(details):
        raise ValueError("Input, reasoned, and facts notice ID sets must match exactly")
    rows, audits = [], []
    for rec in records:
        detail = details[rec["id"]]
        if detail.get("finish_reason") not in ("stop", "mock"):
            raise ValueError("Incomplete facts response cannot be replayed")
        prepared = facts_prepare(rec)
        expected_hash = detail.get("prompt_sha256")
        if expected_hash and prepared.get("prompt_sha256") != expected_hash:
            raise ValueError("Replayed preparation does not match the facts response prompt")
        parsed = parse_result(detail["text"])
        row, changes = fuse_record(rec, baseline[rec["id"]], parsed, prepared["spans"], post_config, product_classifier)
        rows.append(row)
        audits.append({"id": rec["id"], "facts_present": "facts" in parsed,
                       "facts_prompt_sha256": expected_hash, "rule_changes": changes})
    return rows, audits


class _CapturePipeline(Pipeline):
    """Observe the existing prepare call without duplicating inference/retry."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.preparations = {}

    def prepare(self, rec):
        prepared = super().prepare(rec)
        # Recovery mutates this same object only after accepting a new prompt.
        # Retain the reference so replay/evidence use the accepted preparation.
        self.preparations[rec["id"]] = prepared
        return prepared


class TwoPassPipeline:
    """Run reasoned and facts passes with one already-loaded Runner.

    The caller supplies full pass configurations, including output budgets.
    Engine allocation options must match the already-loaded Runner. Native
    thinking is disabled for both structured schemas. The same fixed order is
    used for both passes; only each notice's two results are fused.
    """
    def __init__(self, data_dir, runner, reasoned_config, facts_config, post_config=None):
        self.data_dir, self.runner = data_dir, runner
        self.original_config = deepcopy(runner.config)
        self.reasoned_config = self._pass_config(reasoned_config, "reasoned")
        self.facts_config = self._pass_config(facts_config, "facts")
        # Preserve explicitly requested postprocessing, once after fusion.
        requested = {k: bool(reasoned_config.get(k) or facts_config.get(k)) for k in POST_OPTIONS}
        if post_config is not None:
            requested.update({k: bool(post_config.get(k, False)) for k in POST_OPTIONS})
        self.post_config = requested
        if reasoned_config.get("reasoned_items"):
            reviewed={int(str(v).removeprefix("v")) for v in reasoned_config["reasoned_items"]}
            if set(range(1,25))-reviewed != set(FACT_ITEMS):
                raise ValueError("A split reasoned pass must cover all non-product items")
            self.post_config["facts_baseline"]=True
        self.product_classifier=None
        if requested.get("product_facts"):
            from pps_product_facts import ProvidedProductClassifier
            self.product_classifier=ProvidedProductClassifier(data_dir)

    def _pass_config(self, config, output_format):
        out = deepcopy(config)
        for key in ENGINE_OPTIONS:
            if out.get(key) != self.original_config.get(key):
                raise ValueError(f"Two-pass configuration cannot reallocate loaded engine option: {key}")
        if out["max_model_len"] > self.original_config["max_model_len"]:
            raise ValueError("Pass context exceeds the loaded engine capacity")
        out.update(output_format=output_format, native_thinking=False, apply_facts=False,
                   statutory_rules=False, joint_rules=False, regional_rules=False)
        return out

    def predict(self, records, output_dir, save_details=False):
        records = list(records)
        _unique_index(records, "input")
        if not records:
            raise ValueError("No input notices")
        started = time.monotonic()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temporary = None
        work = output_dir / "passes"
        if not save_details:
            temporary = tempfile.TemporaryDirectory(prefix="pps_twopass_", dir=output_dir)
            work = Path(temporary.name)
        try:
            self.runner.configure(self.reasoned_config)
            reasoned = Pipeline(self.data_dir, self.runner, self.reasoned_config)
            base_report = reasoned.predict(records, work / "reasoned", save_details=save_details)
            with (work / "reasoned/submission.csv").open(encoding="utf-8-sig", newline="") as source:
                base_rows = list(csv.DictReader(source))

            self.runner.configure(self.facts_config)
            factual = _CapturePipeline(self.data_dir, self.runner, self.facts_config)
            # Details contain the successfully parsed response after any normal
            # Pipeline retry; no second parsing/retry implementation is added.
            fact_report = factual.predict(records, work / "facts", save_details=True)
            fact_details = json.loads((work / "facts/model_outputs.json").read_text())
            rows, audits = combine_replay(records, base_rows, fact_details,
                                           lambda rec: factual.preparations[rec["id"]], self.post_config, self.product_classifier)
            csv_path = output_dir / "submission.csv"
            io.write_csv(rows, str(csv_path))
            errors = io.validate_csv(str(csv_path), [r["id"] for r in records])
            if errors:
                raise RuntimeError(str(errors[:10]))
            normal = base_report["normal_model_responses"] + fact_report["normal_model_responses"]
            if not self.runner.mock and normal != 2 * len(records):
                raise RuntimeError("Two normal fixed-model responses per notice were not completed")
            report = {
                "records": len(records), "mode": "mock" if self.runner.mock else "fixed_model",
                "pipeline": "reasoned_then_same_notice_facts", "normal_model_responses": normal,
                "model_load_seconds": self.runner.load_seconds,
                "pipeline_seconds": time.monotonic() - started,
                "retries": base_report["retries"] + fact_report["retries"],
                "recovered_records": base_report["recovered_records"] + fact_report["recovered_records"],
                "compact_recovered_records": base_report["compact_recovered_records"] + fact_report["compact_recovered_records"],
                "generated_tokens": base_report["generated_tokens"] + fact_report["generated_tokens"],
                "prompt_tokens_total": base_report["prompt_tokens_total"] + fact_report["prompt_tokens_total"],
                "rule_changes": sum(len(a["rule_changes"]) for a in audits),
                "facts_missing_records": sum(not a["facts_present"] for a in audits),
                "post_config": self.post_config, "passes": {"reasoned": base_report, "facts": fact_report},
                "format_validation": "PASS",
            }
            (output_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
            if save_details:
                (output_dir / "fusion_details.json").write_text(json.dumps(audits, ensure_ascii=False, indent=2)+"\n")
            return report
        finally:
            self.runner.configure(self.original_config)
            if temporary is not None:
                temporary.cleanup()
