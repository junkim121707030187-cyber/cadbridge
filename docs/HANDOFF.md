# 인계
이 패키지는 개발 준비 문서 1.2.1의 기준선이다. [README](../README.md)→[제품 개념도](PRODUCT_CONCEPT.md)→[요구사항](REQUIREMENTS.md)→[상태·근거](STATUS_AND_EVIDENCE.md)→[검증](VALIDATION.md)→[작업 보드](TASK_BOARD.md) 순으로 읽는다. 작업 규칙은 [AGENTS](../AGENTS.md)에 있다.

## 다음 사람이 할 일
1. 사용자가 지정한 [cadbridge 저장소](https://github.com/junkim121707030187-cyber/cadbridge)의 main 반영 상태·commit을 [상태·근거](STATUS_AND_EVIDENCE.md)에서 확인한다. 파일을 충돌 없이 반영하고 다른 원격을 추측하지 않는다.
2. 공식자료로 CAD 프로그램 두 개의 native 생성·편집·재계산·저장·자동화 가능성을 조사하고 추천안을 만든다. CadQuery/OCCT 같은 라이브러리를 두 CAD 프로그램으로 세지 않는다.
3. 지원 부품·공차 네 종류·판정 절차를 구체화해 추천하고 제품 선택을 받는다. 그 전 최종 성공 판정을 하지 않는다.
4. 후속 구현 권한이 주어지면 T2 수동계획 관문부터 진행한다. M3 활용이 필요하면 실제 소스·전체 증거 archive·해시·의존성·권리를 확보해 대조한다.

## 필요한 자료·오해 방지
원격 주소는 위 지정 저장소로 확인했다. 프로그램 추천 조사 결과, 사용 가능한 native 예제와 STEP 및 이용 권리, 보호 조건·수정 작업, 지원 환경, 권한 정책은 아직 필요하며 확보됐다고 가정하지 않는다. 설계 컨텍스트는 필요한 출처와 요약을 뜻하며 원시 대화 전체·비공개 내부 추론 저장을 뜻하지 않는다.

정본 텍스트 파일과 manifest를 작성했고 별도 seed-docs.json·ZIP을 전달한다. 정적 문서 검토만 했으며 CAD/API 실행은 없다. 기존 M3 코드 이식·회귀 통과·native 성공·다인 workspace·Git 병합 구현으로 해석하지 않는다. 미정 결정은 [DECISIONS](DECISIONS.md)에 모았다. 소유자 결정 전 LICENSE를 추가하지 않는다.

복원 JSON은 manifest를 포함하지 않는다. 복원 후 파일 바이트가 달라지면 manifest를 새로 만들고 버전·작성일·검토 결과를 갱신한다. 해시로 사용자 승인이나 파일 권리를 증명할 수 없다.

## 협업 환경 후속 인계
[CONTRIBUTING](../CONTRIBUTING.md), [에이전트 절차](AGENT_WORKFLOW.md), [작업 카드](tasks/README.md)를 읽는다. 배정 시 기준 commit·수정 경로를 고정한다. 문서 검사는 `python scripts/check_workspace.py`로 수행한다. 실제 GitHub 저장소·CI 결과는 STATUS_AND_EVIDENCE와 WORKSPACE_REVIEW를 기준으로 확인한다.

## 최신 전달 범위
사용자가 이전 중단 이후 업로드를 다시 지시하고 대상 URL을 지정했다. 비공개 cadbridge 저장소의 main에 문서·제품 개념도·협업 파일을 업로드하도록 준비하며, 실제 반영·commit·CI 결과는 [상태·근거](STATUS_AND_EVIDENCE.md)와 [검토 기록](WORKSPACE_REVIEW.md)을 따른다. 이 문구만으로 업로드 완료나 CI 성공을 주장하지 않는다. 이전 직접 업로드용 ZIP과 복원 JSON은 체크포인트로 보존한다. 제품 개념도의 합의·제안·미정 구분과 CAD/API 미검증 범위를 유지한다. GitHub의 개념도 렌더링과 CI 원격 실행은 실제 확인 전까지 미확인이다.
