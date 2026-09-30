# 제출 코드와 정적 자산의 출처

- `pps_io.py`: 대회 배포 `baseline/script.py`를 내용 변경 없이 보존한 모듈. 실행 진입점은 별도 `script.py`이며, 이 모듈의 데이터 로더·메타 포맷·JSON 추출·CSV 함수만 사용한다.
- `pps_context.py`, `pps_examples.py`, `pps_facts.py`, `script.py`: 이번 프로젝트에서 작성한 전처리·검색·고정 모델 추론·후처리 코드. 학습된 추가 가중치는 없다.
- `model/item_guidance.json`: 제공 항목표·법령 스냅샷과 대회 운영진의 공개 해석으로 작성한 지침. 항목별 provenance에 출처가 있다.
- 일반 공고 예시집은 사용하지 않는다(`fewshot_k=0`). 항목별 예시가 활성화된 경우에만 아래의 선택 자산을 포함한다.
- 경쟁제품 CSV는 제출 시 `PPS_DATA_DIR`에 제공되는 파일을 직접 읽는다. 검색 후보는 실제 구매대상과 특이사항을 확인하기 위한 참고이며 확정 분류가 아니다.
- `pps_specialists.py`: 자격(v1~9), 제품(v10~18), 절차(v19~24)를 같은 공고에 대한 세 번의 정상 고정 모델 호출로 검토한다. 자격·절차는 묶음별 원문을 검색하고, 제품은 기존 사실 추출 문맥을 보존한다. 독립 재검토 설정이 활성화되면 미리 정한 정책으로 선택한 같은 공고의 항목만 추가 검토한다. 다른 평가 공고의 내용·예측·통계로 현재 판정을 바꾸지 않는다.
- `pps_frontier.py`: 등록정보와 실제 원문 자격의 역할을 구분하는 지침 및 원문 검색 후보. 제공된 항목표·공고·운영진 해석만 사용하며, 현재 설정에서 선택한 묶음에 적용한다. 외부 법령·입찰·라벨 자료를 가져오지 않는다.
- `pps_fact_invariants.py`: 일반제품에서 신뢰 가능한 원문·등록금액·모델 추출금액의 구간이 일치할 때, 해당 금액구간 밖의 위반을 제거하는 필요조건 검사. 1억원/2.3억원은 제공 항목표의 경계이며 학습된 임계값이 아니다.
- `pps_qualification_logic.py`: 완전히 관측한 자격의 모든 선택지에서 해당 자격이 없을 때 부재를 확인한다. 미해결 참조·불완전 추출·실제 자격 후보·파편 표현이 있으면 확정하지 않는다. 원문 ID나 dev 정답별 예외 규칙은 없다.
- `pps_order.py`: 한 공고 안의 원문을 편집하지 않고 문서ID와 원문 해시로 정렬한다. 문서 배열 순서의 영향을 줄이기 위한 선택 설정이다.
- `pps_enterprise.py`: 기존 사실 추출과 원문 규칙으로 기업 자격이 불확실한 공고에서 직접생산 의무·영리기업 규모·비영리 참가 예외만 별도 추출한다. 제품 종류와 금액은 유지하며, 명시적 자격·예외를 새로 반영하려면 현재 원문의 유효한 근거가 필요하다. 최종 결합은 v10~18만 바꾼다. 정상 compact 복구에 이 사실들이 없으면 기존 결과를 유지한다. 외부 자료·라벨·모델은 사용하지 않는다.
- `pps_verifier.py`: 현재 공고의 원문 인용을 확장해 v1/9/19를 독립적으로 대조한다. 초기 결론·reason을 보여주지 않으며, 재검토할 항목을 정하는 규칙은 고정되어 있다. [Chain-of-Verification](https://arxiv.org/abs/2309.11495)과 [공개 구현 예제](https://github.com/lastmile-ai/aiconfig/tree/main/cookbooks/Chain-of-Verification)의 단계 분리 관점을 참고했다. [자체 재검토의 한계 연구](https://arxiv.org/abs/2310.01798)를 고려해 무조건 전부 교체하는 후보는 실험 후 제외했다. 외부 API 코드는 사용하지 않는다.
- `pps_clause_focus.py`: 현재 공고의 실적·인력·시설 참가요건을 정확한 원문 좌표로 다시 제시한다. 금액 비교는 현재 원문·등록값의 산술 보조이며 계약법·적용 범위·예외를 대신하지 않는다.
- `pps_twopass.py`: 기존 두 번 검토 방식과, 새 방식에서도 사용하는 공고별 사실 결합·조건 검증 함수. 추가 모델·가중치·다른 평가 공고의 예측은 사용하지 않는다.
- `pps_recovery.py`: 실패한 응답에만 실제 남은 컨텍스트 안에서 생성 예산을 확대하고, 필요하면 같은 공고를 고정 길이 v/e 배열과 현재 원문 SID만 허용하는 유한 regex로 재판정한다. 정상 경로의 프롬프트·설정은 유지한다. 잘린 JSON을 수용하거나 임의 라벨로 대체하지 않는다. compact 복구에 의미 사실이 없으면 해당 9항목의 실제 LLM 판단을 보존하며 사실 진리표 보정은 생략한다. 구현 근거는 [vLLM 0.26 구조화 출력 backend](https://github.com/vllm-project/vllm/blob/v0.26.0/vllm/v1/structured_output/backend_xgrammar.py)와 [XGrammar v0.2.3](https://github.com/mlc-ai/xgrammar/tree/v0.2.3)이다.
- `pps_logic.py`, `pps_rules.py`, `pps_region.py`, `pps_regional_rules.py`, `pps_qualification_facts.py`, `pps_product_facts.py`, `pps_procedure_rules.py`, `pps_briefing_dates.py`, `pps_software_rules.py`, `pps_metadata_rules.py`: 제공 항목표·법령·경쟁제품 CSV에 근거한 조건 계산 및 원문 사실 확인. 각 모듈의 출처·주석과 프로젝트 `docs/research/`에 해석·예외·검증 범위를 기록했다. 입력 공고 하나만 읽으며 라벨이나 ID별 예외를 조회하지 않는다.
- `pps_item_examples.py`와 선택 자산 `model/item_examples.json.gz`: 원본 dev 라벨의 항목별 양성/음성 예시 검색. 현재 공고의 동일 ID·본문·거의 같은 전체 본문은 제외한다. 원문 좌표와 원자료 해시는 `model/item_examples_provenance.json`에 있다. 설정에서 사용하는 예시집만 ZIP에 포함한다.

방법론 참고: [Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/), [Least-to-Most Prompting](https://arxiv.org/abs/2205.10625), [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/), [Decomposed Prompting](https://arxiv.org/abs/2210.02406), [KATE](https://aclanthology.org/2022.deelio-1.10/), [LegalBench-RAG](https://arxiv.org/abs/2408.10343), [vLLM 0.26.0](https://docs.vllm.ai/en/v0.26.0/). 해당 연구의 데이터셋·모델 가중치·외부 법령은 사용하지 않았다.

2026-09-07 [운영진 v1 답변](https://dacon.io/competitions/official/236754/talkboard/417321)에 따라 시설·인력의 사전 보유조건과 법정 등록 요건을 구별한다. [캐시 답변](https://dacon.io/competitions/official/236754/talkboard/417337)에 따라 정상 모델 응답을 이전 예측 캐시로 대체하지 않는다. v2의 2.3억원 미만 경계는 제공 법령에 따라 신뢰 가능한 현재 금액·적용 범위에서만 계산한다. 공개 정답의 개별 ID나 숨김 평가 분포에 맞춘 강제 라벨은 없다.

고정 모델: `google/gemma-4-26B-A4B-it`, revision `4d7ae4984b7db7de8f8457170b3f1a419ee76d52`. 가중치는 ZIP에 포함하지 않으며 서버 `PPS_MODEL_DIR`에서 읽는다. 추론 중 네트워크를 사용하지 않는다.

계산 분리의 방법론 참고: [PAL 논문](https://arxiv.org/abs/2211.10435), [PAL 저자 GitHub](https://github.com/reasoning-machines/pal), [Program of Thoughts 논문](https://arxiv.org/abs/2211.12588), [저자 GitHub](https://github.com/TIGER-AI-Lab/Program-of-Thoughts). 생성된 임의 코드를 실행하지 않고 사전에 검토한 함수만 사용한다.

2026-09-09 후속 구현:
- `pps_priority.py`: 제공 법령·항목표를 근거로 현재 주 공고에 명시된 우선조달 예외 적용 문장을 확인한다. 부정·조건·인용·공통 첨부 문구는 제외하고 v16/v18의 자격 부재 판단에만 적용한다. 외부 법령이나 공고 ID별 예외는 없다.
- `pps_enterprise.py`의 선택적 `strict_scope_evidence`: 신규 기업 범위의 자체 인용이 기존 범위만 명시적으로 지지할 때 모순된 덮어쓰기를 보류한다. 모호한 인용이나 unknown을 정답으로 강제하지 않는다.
- `pps_verifier.py`의 집중 검토 및 원문 SID 형식 제한: 이전 양성으로 선택된 현재 항목의 주체·의무·시점·예외만 다시 확인한다. 문법상 SID와 실제 원문 지지는 별도로 검사한다.
- `pps_sentinel.py`, `pps_product_checks.py`: 길이가 제한된 재독해·출력 순서·제품 항목 이유·SID 스키마의 선택적 구현. 최종 `model/config.json`에서 활성화한 기능만 실행한다. [Re2](https://arxiv.org/abs/2309.06275), [구조화 규칙 적용 연구](https://arxiv.org/abs/2506.16335), [저자 GitHub](https://github.com/albsadowski/structured-decomposition)를 방법론으로 참고했으며 해당 자료의 데이터·가중치·코드는 가져오지 않았다.
- BGE-M3는 제공 경쟁제품 CSV의 검색 후보 실험에만 사용했다. 최종 제출에는 BGE 모델·검색 캐시·추가 데이터가 없으며 추론에서 BGE를 호출하지 않는다.
