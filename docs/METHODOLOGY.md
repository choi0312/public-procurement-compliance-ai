# 방법론 상세

## 문제 정의

입력 공고 (x_i)는 meta와 여러 원문 문서로 구성됩니다. 출력은 24개 이진 판정

\[
\hat{y}_i = (\hat{y}_{i1}, \ldots, \hat{y}_{i24}),\quad \hat{y}_{ij}\in\{0,1\}
\]

과 양성 판정을 뒷받침하는 원문 근거 (e_{ij})입니다. 평가는 24개 항목의 positive-class F1 평균입니다.

\[
\text{MacroF1}=\frac{1}{24}\sum_{j=1}^{24}
\frac{2TP_j}{2TP_j+FP_j+FN_j}
\]

항목별 양성 수가 적고, 한 공고 안에서도 참가자격·제품·계약절차의 언어가 크게 다릅니다. 하나의 긴 프롬프트가 24개 항목을 동시에 판단하면 다음 오류가 섞였습니다.

- 등록정보와 실제 참가자격을 혼동
- 제품 등록 코드와 실제 구매대상을 혼동
- 계약 후 제출과 입찰 전 보유 의무를 혼동
- OR 자격의 한 분기를 전체 의무로 일반화
- 금액 단위와 부가세 기준을 잘못 결합
- 결론은 맞지만 존재하지 않는 인용을 생성

이 프로젝트는 이 오류를 **분해, 제한된 사실 추출, 결정 규칙, 근거 검증**의 네 층으로 나눴습니다.

## 1. 업무 의미에 따른 고정 분해

[Decomposed Prompting](https://arxiv.org/abs/2210.02406)과 [Least-to-Most Prompting](https://arxiv.org/abs/2205.10625)은 복잡한 문제를 하위 문제로 나누는 일반 전략을 제시합니다. 여기서는 모델이 하위 문제를 즉석에서 만들게 하지 않고, 24개 평가 항목의 의미를 기준으로 다음 세 묶음을 고정했습니다.

| specialist | 항목 | 주된 질문 |
|---|---|---|
| qualification | v1–v9 | 누가 참가할 수 있고 무엇을 입찰 전에 갖춰야 하는가 |
| products | v10–v18 | 실제 구매대상은 무엇이며 경쟁제품·직생·기업 범위 조건은 무엇인가 |
| procedure | v19–v24 | 확약·설명회·공동수급·SW 문구·meta 일치 조건은 무엇인가 |

세 묶음은 모든 항목을 정확히 한 번 담당합니다. 모델과 revision은 같지만 시스템 지침, 원문 선택, 출력 schema가 다릅니다. 이 구조는 하위 결과를 다시 자연어로 요약하지 않고 항목 번호와 구조화 facts로 결합하므로 전달 과정의 정보 손실을 줄입니다.

## 2. LLM을 사실 추출기로 제한

[Explainable Rule Application via Structured Prompting](https://arxiv.org/abs/2506.16335)은 entity identification, property extraction, rule application을 분리합니다. [2026년 후속 연구](https://arxiv.org/abs/2601.01609)는 LLM을 ontology population에, symbolic reasoner를 결정에 쓰는 패턴을 여러 도메인으로 확장했습니다.

본 구현은 OWL/SWRL을 쓰지 않지만 같은 경계를 더 가벼운 경진대회 런타임에 맞게 적용합니다.

1. 모델은 현재 공고의 제한된 사실을 enum으로 추출합니다.
2. `yes/no/unknown`과 범주형 값의 schema를 decoding 단계에서 강제합니다.
3. 사람이 검토한 Python 함수가 항목별 필요조건과 예외를 계산합니다.
4. 알려지지 않은 사실은 `unknown`으로 유지하고 기존 모델 판정을 함부로 지우지 않습니다.

제품 pass의 대표 facts는 실제 제품 유형, 추정가격 구간, 직접생산 요구, 영리기업 규모, 비영리 예외, 특수 조건입니다. 자격과 절차는 항목별 reason·v·SID를 구조화합니다.

## 3. 생성과 계산의 분리

[PAL](https://arxiv.org/abs/2211.10435)과 [Program of Thoughts](https://arxiv.org/abs/2211.12588)는 언어 모델이 계산 절차를 분리하도록 합니다. 이 프로젝트는 생성된 프로그램을 실행하는 대신, 대회 제공 기준에서 미리 작성하고 테스트한 함수만 실행합니다.

- 원화 단위 통일과 1억/2.3억 구간
- 설명회 날짜와 입찰 마감일 비교
- 참가자격 OR 분기의 폐쇄 여부
- 지역 제한과 적용 지역
- 실제 제품과 제공 경쟁제품 CSV 조건
- SW 사업의 원문 또는 제안요청서 근거 존재
- 명시적 우선조달 예외의 적용 범위

결정 함수는 양성·음성을 새로 추측하기보다 **명백한 필요조건 위반을 제거하거나, 원문으로 확인된 제한된 조건을 추가**하는 방식입니다. `unknown`과 abstention을 구별한 이유는 부재 증명이 존재 증명보다 더 많은 관측을 요구하기 때문입니다.

## 4. 근거를 출력 계약으로 사용

[ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)와 2025년 [사실–증거 구조 법률추론 벤치마크](https://aclanthology.org/2025.findings-acl.887/)는 결론과 근거의 연결을 평가 가능한 형태로 다룹니다. 2026년 [Korean Canonical Legal Benchmark](https://aclanthology.org/2026.eacl-short.17/)도 문제별 supporting precedent를 제공해 기억 지식과 주어진 근거를 분리합니다.

이 구현에서는 선택된 원문 span마다 `s001` 형식 SID와 원래 문서 좌표를 보존합니다. 모델은 SID 또는 `SID|짧은 인용`을 반환하며, 후처리는 다음을 확인합니다.

- SID가 현재 공고의 선택 span에 존재하는가
- 인용이 그 span과 단일 원문 문서에 문자 그대로 존재하는가
- 길이가 500자 이하인가
- CSV formula injection 위험 문자인 `=`, `+`, `@`로 시작하지 않는가
- 양성 항목이며 근거 허용 항목인가

검증을 통과하지 못한 인용은 빈칸으로 바뀝니다. 모델이 만든 그럴듯한 설명은 증거로 저장되지 않습니다.

## 5. 선택적 독립 검증

[Chain-of-Verification](https://arxiv.org/abs/2309.11495)은 초안과 검증 단계를 분리합니다. 그러나 ICLR 2025의 [self-verification 한계 연구](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f3c5e56274140e0420baa3916c529210-Abstract-Conference.html)는 같은 모델의 반복 자기비평이 항상 개선을 만들지 않으며, sound external verification이 더 중요하다는 결과를 보고합니다.

이를 반영해 검증 범위를 제한했습니다.

- 사전에 고정한 v1·v9·v19만 대상
- 1차 결합이 양성인 항목만 재검토
- 이전 label과 reason은 verifier prompt에 넣지 않음
- 현재 공고 원문과 candidate quote 주변만 확대
- 주체·의무·시점·예외를 새로 추출
- 새 SID가 실제 원문을 가리킬 때만 해당 항목 교체

모든 항목을 여러 번 재작성하는 self-refine loop를 쓰지 않은 것은 정확도와 시간뿐 아니라 오류 상관을 줄이기 위한 선택입니다.

## 6. 긴 문맥의 선택과 정렬

[Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/)은 긴 입력에서 관련 정보의 위치가 성능에 영향을 줄 수 있음을 보였습니다. 본 구현은 전체 문서를 단순 절단하지 않고 다음 우선순위를 사용합니다.

1. 항목별 핵심 표현 주변의 정확한 원문 구간
2. 공고 제목과 참가자격·제품·절차 섹션
3. meta와 원문이 충돌할 때 실제 적용값이 적힌 주 공고
4. 남은 문자 예산 안의 보조 문서

동일 공고의 문서 배열은 문서 ID와 원문 해시로 정렬합니다. 원문 문자는 바꾸지 않습니다. 문서 예산을 14,000자에서 22,000자로 늘리는 실험은 더 느리고 전체 F1이 낮았으므로 최종 설정에 넣지 않았습니다.

## 7. 구조 제약과 bounded recovery

vLLM 0.26.0과 XGrammar 0.2.3의 JSON Schema constrained decoding을 사용합니다. 정상 경로는 schema, 종료 이유, 생성 토큰 수, JSON 내용, 배열 길이와 타입을 모두 검증합니다.

복구는 오류가 있는 응답에만 적용합니다.

1. 남은 context 안에서 output token budget 확대
2. reason과 facts를 제거한 24개 `v/e` compact schema
3. 현재 공고의 SID와 `null`만 허용하는 finite regex

각 복구도 새로운 정상 모델 호출이어야 합니다. 부분 응답을 파싱해 빈 항목을 0으로 채우거나 이전 공고의 캐시를 재사용하지 않습니다. [De Jure](https://arxiv.org/abs/2604.02276)의 bounded repair와 구조적으로 가깝지만, 본 구현은 LLM-as-a-judge의 반복 점수화 대신 기계 검증 실패에만 복구를 시작합니다.

## 8. 최종적으로 제외한 방법

- **Re2 재독해:** 같은 기준을 다시 배치했지만 dev F1이 낮고 느렸습니다.
- **전면 predicate 분해:** 더 많은 이유 필드가 제품 판정을 안정화하지 못했습니다.
- **BGE-M3 retrieval:** 제공 CSV 검색은 빨랐지만 제품군 F1이 대조군보다 낮았습니다.
- **전체 BF16 또는 혼합 KV:** FP8보다 느렸고 정확도 이득이 없었습니다.
- **batch invariance:** 당시 vLLM beta 기능이며 Gemma 4가 명시 검증 대상이 아니었고, 실제 실행도 느리고 낮았습니다.
- **제품별 추가 reason:** 전체 점수의 작은 상승과 달리 실제 변경 대상인 제품 9개 평균 F1이 하락했습니다.

제외한 결과를 보존한 이유는 방법의 일반적 무효를 주장하기 위해서가 아니라, 이 모델·이 데이터·이 시간제한에서 채택하지 않은 근거를 남기기 위해서입니다.
