"""Bounded same-notice recovery. Never turn an incomplete response into labels."""
from copy import deepcopy
import hashlib
import json
import re
import sys


MARGIN = 128
COMPACT_INSTRUCTION = """
[이번 응답의 최종 출력 형식: 짧은 복구 형식]
앞의 설명형/facts 출력 형식 대신 이번에는 아래 JSON 하나만 출력한다.
현재 공고와 위 판정 기준을 그대로 검토하여 v1~v24 순서의 정수0/1을 정확히24개 채운다.
{"v":[24개 판정],"e":[24개 근거]}
reason, facts, 해설, 원문 인용문은 출력하지 않는다. e에는 현재 공고의 원문 구간ID만 고른다.
e는 비위반·부재형10/11/16/18/20·적합한 구간이 없으면null이다. 참고사례의 구간을 사용하지 않는다.
"""


def _check(result, runner, parse, selected):
    expected = {"stop", "mock"} if runner.mock else {"stop"}
    if result.get("finish_reason") not in expected:
        raise ValueError("incomplete response: " + str(result.get("finish_reason")))
    if not runner.mock and result.get("generated_tokens", 0) <= 0:
        raise ValueError("empty generated response")
    return parse(result["text"], selected)


def compact_schema(spans):
    ids = list(dict.fromkeys(s["sid"] for s in spans))
    if any(not re.fullmatch(r"s\d{1,8}", sid) for sid in ids):
        raise ValueError("Invalid current-notice source ID")
    return {"type": "object", "additionalProperties": False, "required": ["v", "e"],
            "properties": {
                "v": {"type": "array", "minItems": 24, "maxItems": 24,
                      "items": {"type": "integer", "enum": [0, 1]}},
                "e": {"type": "array", "minItems": 24, "maxItems": 24,
                      "items": {"enum": [None] + ids}},
            }}


def compact_regex(schema):
    """Equivalent finite ASCII JSON language, including a fixed whitespace policy.

    vLLM 0.26 may use the engine-level whitespace setting for JSON schemas.
    A request-level regex makes this rescue independent of that setting and
    excludes unbounded whitespace, quotes and numeric/string expansion.
    """
    values = schema["properties"]["e"]["items"]["enum"]
    if not values or values[0] is not None or any(not isinstance(s, str) or not re.fullmatch(r"s\d{1,8}", s) for s in values[1:]):
        raise ValueError("Recovery regex accepts only null and current source IDs")
    evidence = "(" + "|".join("null" if s is None else re.escape(json.dumps(s)) for s in values) + ")"
    return r'\{"v":\[[01](,[01]){23}\],"e":\[' + evidence + "(," + evidence + r'){23}\]\}'


def complete_response(runner, prepared, initial_result, config, parse):
    """Return one accepted raw response, parsed object and recovery call history.

    Successful first responses are returned without counting/reformatting prompts
    or changing sampling state. On compact recovery, mutate only this preparation
    to identify the prompt that actually produced the accepted raw response.
    Every recovery is a fresh meaningful model judgment of this same notice.
    """
    selected = config.get("reasoned_items") if config.get("output_format") == "reasoned" else None
    try:
        return initial_result, _check(initial_result, runner, parse, selected), []
    except (ValueError, KeyError, TypeError) as exc:
        initial_error = type(exc).__name__
    initial = {"stage": "initial", "finish_reason": initial_result.get("finish_reason"),
               "generated_tokens": initial_result.get("generated_tokens", 0),
               "prompt_tokens": prepared["prompt_tokens"], "max_tokens": config["max_output_tokens"],
               "error_type": initial_error}
    print("[pps] recovering response " + json.dumps(initial), file=sys.stderr, flush=True)
    attempts = []

    def attempt(stage, prompt, budget, schema=None):
        if budget < 1 or prompt["prompt_tokens"] + budget + MARGIN > config["max_model_len"]:
            raise ValueError("Recovery budget exceeds actual context space")
        record = {"stage": stage, "max_tokens": budget, "prompt_tokens": prompt["prompt_tokens"],
                  "finish_reason": None, "generated_tokens": 0,
                  "prompt_sha256": prompt["prompt_sha256"]}
        try:
            kwargs = {"max_tokens": budget}
            if schema is not None:
                kwargs["output_schema"] = schema
            outputs = runner.generate([prompt["messages"]], **kwargs)
            if len(outputs) != 1:
                raise ValueError("Recovery returned the wrong number of responses")
            result = outputs[0]
            record.update(finish_reason=result.get("finish_reason"), generated_tokens=result.get("generated_tokens", 0))
            obj = _check(result, runner, parse, selected)
            if schema is not None:
                # Do not accept a runner/backend that ignored the finite schema.
                if set(json.loads(result["text"])) != {"v", "e"}:
                    raise ValueError("Recovery did not produce the compact schema")
                allowed = schema["properties"]["e"]["items"]["enum"]
                if any(value not in allowed for value in obj["e"]):
                    raise ValueError("Recovery evidence is not from this notice")
            record["accepted"] = True
            attempts.append(record)
            return result, obj
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            record.update(accepted=False, error_type=type(exc).__name__)
            attempts.append(record)
            print("[pps] recovery attempt " + json.dumps(record), file=sys.stderr, flush=True)
            return None

    available = config["max_model_len"] - prepared["prompt_tokens"] - MARGIN
    expanded = min(available, int(config.get("recovery_max_tokens", 8192)))
    if expanded > 0 and (expanded > config["max_output_tokens"] or initial_result.get("finish_reason") != "length"):
        accepted = attempt("expanded", prepared, expanded)
        if accepted is not None:
            return *accepted, attempts

    compact = dict(prepared)
    compact["messages"] = deepcopy(prepared["messages"])
    system = next((m for m in compact["messages"] if m["role"] == "system"), None)
    if system is None:
        compact["messages"].insert(0, {"role": "system", "content": COMPACT_INSTRUCTION})
    else:
        system["content"] += "\n" + COMPACT_INSTRUCTION
    compact["prompt_tokens"] = runner.count(compact["messages"])
    compact["prompt_sha256"] = hashlib.sha256(json.dumps(compact["messages"], ensure_ascii=False).encode()).hexdigest()
    schema = compact_schema(compact["spans"])
    available = config["max_model_len"] - compact["prompt_tokens"] - MARGIN
    tried = set()
    for cap in (2048, 4096):
        budget = min(available, cap)
        if budget < 256 or budget in tried:
            continue
        tried.add(budget)
        accepted = attempt("compact", compact, budget, schema)
        if accepted is not None:
            prepared.update(compact)
            return *accepted, attempts
    diagnostic = {"format": config.get("output_format"), "initial": initial, "attempts": attempts}
    raise RuntimeError("Unable to obtain a complete validated model response after bounded recovery: " +
                       json.dumps(diagnostic, ensure_ascii=False))
