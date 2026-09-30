# 구현 안내

`submission/`은 최신 제출 ZIP과 바이트 단위로 같아 공개 문서 작성 과정에서 source를 수정하지 않았습니다. 모든 Python 모듈에는 역할과 데이터 경계를 설명하는 module docstring이 있고, 법적 조건이나 보수적 abstention이 필요한 지점에는 inline comment가 있습니다.

## 호출 순서

1. `script.py::main`
2. `pps_io.iter_records`
3. `script.Runner`가 Gemma/vLLM/XGrammar 초기화
4. `pps_specialists.SpecialistEnsemble.predict`
5. qualification/products/procedure의 `SpecialistPipeline.predict`
6. `pps_twopass.fuse_record`와 항목별 rule modules
7. `pps_verifier.VerificationPipeline`의 선택 재검토
8. `pps_enterprise.EnterprisePipeline`의 조건부 facts 보강
9. `script.resolve_row`의 evidence 원문 검증
10. `pps_io.write_csv`와 `pps_io.validate_csv`

## 핵심 모듈

| 모듈 | 책임 | 중요한 불변조건 |
|---|---|---|
| `script.py` | engine, prompt schema, batch 실행, CSV | 한 입력당 정상 model response; 엄격한 JSON 타입 |
| `pps_io.py` | 데이터 로딩·출력 | 49열, ID 보존, NFC |
| `pps_context.py` | 원문 span 선택 | 원문 좌표 보존, 문자 예산 |
| `pps_order.py` | 문서 고정 정렬 | 같은 공고 내부만 사용, 원문 불변 |
| `pps_specialists.py` | 3개 specialist 실행·결합 | 24개 항목을 정확히 한 번 담당 |
| `pps_frontier.py` | source role 분리 | 등록정보와 실제 참가요건 구별 |
| `pps_product_facts.py` | 제공 CSV와 실제 구매대상 대조 | 등록/certificate 코드만으로 제품 확정 금지 |
| `pps_qualification_facts.py` | 참가자격 literal facts | 부재는 완전 관측과 닫힌 section 필요 |
| `pps_qualification_logic.py` | OR 분기의 부재 판정 | 미해결 참조가 있으면 abstain |
| `pps_logic.py` | structured facts validation·truth table | `unknown`은 임의 label로 바꾸지 않음 |
| `pps_fact_invariants.py` | 제품 금액 필요조건 | 음성 제거만 수행, 양성 추정 금지 |
| `pps_rules.py` | 제공 법령 기반 좁은 보정 | 현재 공고만 읽고 ID/label rule 없음 |
| `pps_regional_rules.py` | 지역 제한 보정 | positive-only, 모호하면 abstain |
| `pps_procedure_rules.py` | v19/v22 절차 보정 | 시점과 참가 의무를 원문으로 확인 |
| `pps_briefing_dates.py` | v23 날짜 계산 | 시스템 현재 연도 추정 금지 |
| `pps_software_rules.py` | v20 원문 근거 | 누락된 RFP가 있으면 부재 확정 금지 |
| `pps_metadata_rules.py` | v24 meta–원문 대조 | 네 축이 모두 확인될 때만 음성 확정 |
| `pps_priority.py` | v16/v18 우선조달 예외 | 현재 주 공고의 명시적 적용 문장만 인정 |
| `pps_verifier.py` | v1/v9/v19 독립 재검토 | 이전 label/reason 비공개 |
| `pps_enterprise.py` | 직생·규모·비영리 재추출 | 자체 인용과 범주가 모순되면 변경 거부 |
| `pps_recovery.py` | 오류 응답 복구 | incomplete response를 label로 수용하지 않음 |

## 설정 해석

최종 [`config.json`](../submission/model/config.json)의 주요 switch는 다음과 같습니다.

| 설정 | 값 | 의미 |
|---|---:|---|
| `specialist_pipeline` | true | 3개 묶음 분해 사용 |
| `canonical_document_order` | true | 한 공고 내 문서 정렬 |
| `fact_invariants` | true | 알려진 제품 필요조건 적용 |
| `qualification_disjunction_absence` | true | 닫힌 OR 전체의 부재 검사 |
| `independent_verification` | true | v1/v9/v19 gate 사용 |
| `verification_policy` | positive_only | 기존 양성만 검토 |
| `independent_enterprise` | true | 불확실한 제품 자격 facts 재추출 |
| `explicit_priority_exemption` | true | 명시적 v16/v18 예외 반영 |
| `focus_review_items` | true | verifier를 실제 선택 항목에 집중 |
| `verification_source_id_only` | true | verifier evidence를 SID 문법으로 제한 |
| `fewshot_k` | 0 | 일반 dev 예시 미사용 |
| `item_example_items` | null | 항목별 dev 예시 미사용 |
| `batch_invariant` | false | 실험 결과 느리고 낮아 비활성 |

루트 `native_thinking=true`는 Gemma reasoning parser를 engine 초기화 시 사용할 수 있게 하는 값입니다. 실제 세 specialist, verifier, enterprise pass는 `native_thinking=false`, `thinking_token_budget=0`으로 다시 구성됩니다.

## 수정할 때 지켜야 할 계약

1. `submission/model/config.json`을 단일 활성 설정으로 유지합니다.
2. 새 rule은 현재 공고와 제공 자료만 읽어야 합니다.
3. absence 보정은 완전 관측을 증명하지 못하면 abstain해야 합니다.
4. evidence는 `script.resolve_row`를 통과해야 합니다.
5. 새 model pass는 정상 응답 수와 recovery를 `run_report.json`에 포함해야 합니다.
6. ZIP은 `scripts/package_submission.py`의 allowlist로만 만듭니다.
7. 변경 후 `scripts/test_submission_contract.py`와 실제 GPU recovery 검사를 실행합니다.
