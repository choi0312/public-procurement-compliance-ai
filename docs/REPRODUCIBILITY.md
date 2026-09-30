# 재현 안내

## 공개 범위

이 저장소의 `submission/`은 최신 `submission_sentinel.zip`의 33개 member를 풀어 놓은 것입니다. 공개 저장소에서는 다음을 제외합니다.

- DACON 원본·파생 데이터와 dev 라벨
- dev 예시와 provenance 자산
- Gemma/BGE 모델 가중치와 cache
- 모델 응답, 예측 CSV, 실행 artifact
- Runpod API key와 운영 스크립트

최종 설정은 `fewshot_k=0`, `item_example_items=null`이므로 제외한 dev 예시 자산은 추론에 필요하지 않습니다.

## 고정 정보

| 항목 | 값 |
|---|---|
| model | `google/gemma-4-26B-A4B-it` |
| revision | `4d7ae4984b7db7de8f8457170b3f1a419ee76d52` |
| Python | 3.12 |
| vLLM | 0.26.0 |
| PyTorch | 2.11.0+cu130 |
| Transformers | 5.14.1 |
| XGrammar | 0.2.3 |
| GPU 실측 | NVIDIA L40S 48GB × 1 |
| `max_model_len` | 24,576 |
| weight quantization | `int8_per_channel_weight_only` |
| KV cache | FP8, runtime scale 계산 |
| batch | 최대 8,192 tokens / 32 sequences |
| specialist thinking | disabled, budget 0 |

구성의 단일 기준은 [`submission/model/config.json`](../submission/model/config.json)입니다.

## 데이터 배치

DACON 배포 파일을 직접 내려받아 다음 환경변수를 지정합니다.

```bash
export PPS_DATA_DIR=/absolute/path/to/official/data
export PPS_OUTPUT_DIR=/absolute/path/to/output
export PPS_MODEL_DIR=/absolute/path/to/google-gemma-4-26B-A4B-it
```

코드는 네트워크를 끄기 위해 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`을 설정하고, `PPS_MODEL_DIR`이 실제 디렉터리가 아니면 즉시 실패합니다.

## 빠른 계약 검사

GPU와 대회 데이터가 없어도 JSON/CSV/ZIP 보안 계약을 확인할 수 있습니다.

```bash
python scripts/test_submission_contract.py
python scripts/package_submission.py --output /tmp/submission.zip
PPS_AUDIT_ZIP=/tmp/submission.zip python scripts/test_submission_contract.py
```

테스트는 다음을 검사합니다.

- 24개 이진 label과 evidence 배열의 엄격한 타입
- Gemma reasoning channel 뒤 final JSON만 수용
- 원문에 없는 인용과 문서 경계 합성 거부
- 49열 CSV와 ID 정렬
- 부재형 evidence 빈칸
- 실패 응답의 bounded recovery
- ZIP 내 raw data, model weight, secret signature, unsafe path 부재

GitHub Actions의 `public-contracts` workflow도 같은 검사를 수행합니다.

## mock 실행

mock은 입출력과 pipeline wiring만 확인합니다. 정확도나 실제 model response를 재현하지 않습니다.

```bash
python submission/script.py \
  --mock \
  --limit 3 \
  --config submission/model/config.json \
  --output-dir /tmp/pps-mock \
  --save-details
```

## 실제 실행

```bash
python submission/script.py \
  --config submission/model/config.json \
  --output-dir "$PPS_OUTPUT_DIR" \
  --save-details
```

실행 중 외부 API를 호출하지 않습니다. 성공 조건은 다음과 같습니다.

1. 입력 ID마다 기본 3개의 정상 specialist 응답
2. gate가 선택한 경우에만 정상 verifier/enterprise 응답
3. 모든 accepted response의 schema와 finish reason 검증
4. `submission.csv`의 49열·ID·binary label·evidence 원문성 검증
5. `run_report.json` 생성

## 평가

공개 dev truth와 예측이 있을 때만 다음을 사용합니다.

```bash
python scripts/evaluate.py \
  /path/to/dev_labels.csv \
  /path/to/submission.csv \
  --output /tmp/dev_metrics.json
```

이 스크립트는 ID를 엄격히 맞춘 뒤 v1–v24 positive-class Macro F1을 계산합니다.

## ZIP 생성

```bash
python scripts/package_submission.py --output /tmp/submission.zip
```

packager는 Python source, `requirements.txt`, `SOURCES.md`, 활성 설정과 지침만 allowlist로 넣습니다. dev 예시 자산은 설정에서 실제 활성화된 경우에만 추가되지만, 공개 최종 설정에서는 비활성입니다. ZIP 생성 후 실제 archive member를 다시 감사합니다.

## 재현성의 범위

동일 prompt hash, temperature 0, seed 고정에도 GPU kernel과 dynamic batching에 따라 일부 출력이 달랐습니다. 최종 공개 1,853건 실행은 6,390.95초였지만 다음 조건이 완전히 같아야 시간 비교가 의미가 있습니다.

- 동일 GPU와 드라이버
- 동일 vLLM/PyTorch/Transformers/XGrammar
- 동일 모델 revision과 양자화 경로
- 동일 CPU affinity와 동시 부하
- 동일 kernel cache 및 OS page cache 상태

이 저장소는 코드·설정·출력 계약을 재현할 수 있게 하지만 bitwise label 재현성을 보증하지 않습니다.
