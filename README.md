# CADBridge 개발 준비 정본
문서 기준선 1.2.1 + 분담 인수인계 0.1.0 · 2026-11-16 KST

서로 다른 CAD 프로그램·버전을 사용하는 기업체와 팀이 설계와 변경 이력을 공유하고 이어서 편집하는 협업 워크스페이스를 목표로 한다. 첫 단계는 STEP에서 편집 가능한 오픈소스 CAD native 부품을 재구성하는 것이다. 이후 서로 다른 오픈소스 CAD 프로그램 사이로 설계 맥락과 제약을 이전한다.

초기 1.2.1 기록: 문서·제품 개념도와 협업 작업 환경 파일 33개를 사용자 지정 비공개 [cadbridge 저장소](https://github.com/junkim121707030187-cyber/cadbridge)의 main에 반영하고 원격 파일 해시를 대조했다. 당시 프로그램 선정·CAD/API 실행·M3 소스 이식은 하지 않았다. 실제 commit·문서 검사·CI 상태는 [상태·근거](docs/STATUS_AND_EVIDENCE.md)를 따른다.

후속 합의와 이번 추가분: 사용자는 FreeCAD 1.1.4·SALOME SHAPER 9.16.0, CB-P01 부품·공차를 채택했다. [세 파트 인수인계](docs/MODULE_HANDOFFS.md)에 최신 기준과 AI 연결·UIUX·기계 제약 ZIP을 정리했다. AI 묶음에는 M3 관련 원문 23파일을 참고용으로 선별했고 전체 코드 이식이나 새 실행 성공을 뜻하지 않는다. LICENSE는 소유자 결정 전 만들지 않는다.

## 읽는 순서
1. [제품 개념도와 미정 사항](docs/PRODUCT_CONCEPT.md), [제품 개요](docs/PROJECT_BRIEF.md)와 [요구사항](docs/REQUIREMENTS.md)
2. [결정 로그](docs/DECISIONS.md)와 [현재 상태·근거](docs/STATUS_AND_EVIDENCE.md)
3. [구조 제안](docs/ARCHITECTURE.md), [데이터·컨텍스트](docs/DATA_AND_CONTEXT.md), [AI 정책](docs/AI_POLICY.md)
4. [검증 관문](docs/VALIDATION.md), [개발 절차](docs/DEVELOPMENT_WORKFLOW.md), [작업 보드](docs/TASK_BOARD.md)
5. 작업 전 [AGENTS](AGENTS.md), 인계 시 [HANDOFF](docs/HANDOFF.md)

## 패키지 사용
ZIP을 풀고 cadbridge-seed/ 안의 파일과 폴더를 사용자가 만든 Git 저장소 루트에 복사하거나 업로드한다. 기존 파일과 충돌하면 비교 후 반영한다. cadbridge-seed 폴더 자체를 이중 중첩하지 않는다. 전달 ZIP에는 이 폴더와 별도 seed-docs.json이 들어 있다. JSON은 업로드 필수 파일이 아닌 복원용 사본이며 manifest와 archive를 제외한 정본 텍스트 파일을 보존한다. 복원 시 path를 상대 경로로 한정하고 절대경로·상위 경로 탈출·중복 경로를 거부한 뒤 UTF-8로 저장한다. GitHub에서는 PRODUCT_CONCEPT.md의 Mermaid 개념도를 볼 수 있다.

[BUNDLE_MANIFEST.json](BUNDLE_MANIFEST.json)의 files에는 저장소 내부 파일의 SHA256을, recovery에는 별도 복원 JSON의 SHA256을 기록한다. `python scripts/check_workspace.py --verify-manifest`는 저장소 내부 파일을 검사하므로 복원 JSON 없이 업로드한 뒤에도 실행할 수 있다. 자기 자신과 ZIP은 순환 해시를 피하기 위해 제외한다. 파일 해시는 무결성 확인용이며 승인·신원 인증 수단이 아니다.

## 협업 환경 시작
[CONTRIBUTING](CONTRIBUTING.md)에서 사람용 절차를 읽고 [에이전트 작업 절차](docs/AGENT_WORKFLOW.md), [계약 목록](docs/INTERFACES.md), [작업 카드](docs/tasks/README.md)를 사용한다. [참고 저장소 검토](docs/REFERENCE_REVIEW.md)에 적용·제외 근거가 있다.

문서 검사: `python scripts/check_workspace.py` (Python 3.11 이상, 추가 설치 없음). GitHub CI도 같은 검사만 수행한다. CAD/API 호출·자동 배포·자동 merge는 없다. 초기 작업은 [CB-001 프로그램 조사](docs/tasks/CB-001.md)이며 아직 미배정·미시작이다.

## 분담 인수인계 모듈
후속 사용자 요청에 따른 [AI 연결·UIUX·CAD 기계 제약 인수인계](docs/MODULE_HANDOFFS.md)를 추가했다. 각 파트의 독립 전달 ZIP과 최신 CAD·부품·공차 채택, 역할 경계·열린 결정은 해당 안내를 따른다. 이 추가분은 새 런타임 구현이나 CAD/API 실행 성공이 아니다.
