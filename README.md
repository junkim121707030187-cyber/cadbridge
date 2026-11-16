# CADBridge · 로컬 통합 시제품

2026-11-16 업데이트: STEP 관측·Terra 후보·FreeCAD native 모델과 Slack을 모티브로 한 파일·형상 워크스페이스를 `prototype/`에 추가했습니다. 현재 각 Windows PC에서 설치해 살펴보기 위한 소스·예제 묶음이며, 팀원 PC 실행 확인은 후속 작업입니다.

- **처음 받는 팀원:** [설치·실행 안내](prototype/README.md)
- **AI가 실제 작업한 예제:** [CB-P01 입력·Terra 응답·편집 전후 결과](prototype/examples/AI_EXAMPLE.md)
- **공유 보고서:** [진척도와 파트별 후속 작업 DOCX](deliverables/CADBridge_구현진척과_파트별후속작업_2026-11-16.docx)
- **통합 소스·예제 ZIP:** [배포 스냅샷](deliverables/CADBridgeWorkspace_MVP_소스와예제.zip)
- **변경·한계:** [업로드 인계](docs/PROTOTYPE_UPLOAD_2026-11-16.md)

예제의 저장 결과는 포함했습니다. Python·FreeCAD 실행 환경과 개인 AI 계정은 포함하지 않았으므로 최초 설치가 필요합니다. 각 PC의 작업은 서로 자동 동기화되지 않습니다. 이번 업로드에서는 새 실행 검사를 수행하지 않았습니다.

## 기존 개발 준비 기록

아래는 이번 시제품 추가 이전의 문서 1.2.1 기준선입니다. 당시 ‘구현 없음’ 표기는 아래 과거 체크포인트의 범위입니다. 최신 시제품 상태는 위 안내와 `prototype/evidence`를 참고하세요.

# CADBridge 개발 준비 정본
문서 버전 1.2.1 · 2026-11-16 KST

서로 다른 CAD 프로그램·버전을 사용하는 기업체와 팀이 설계와 변경 이력을 공유하고 이어서 편집하는 협업 워크스페이스를 목표로 한다. 첫 단계는 STEP에서 편집 가능한 오픈소스 CAD native 부품을 재구성하는 것이다. 이후 서로 다른 오픈소스 CAD 프로그램 사이로 설계 맥락과 제약을 이전한다.

문서·제품 개념도와 협업 작업 환경 파일 33개를 사용자 지정 비공개 [cadbridge 저장소](https://github.com/junkim121707030187-cyber/cadbridge)의 main에 반영했다. 원격 파일 해시를 로컬 원본과 대조했다. 실제 commit·문서 검사·CI 상태는 [상태·근거](docs/STATUS_AND_EVIDENCE.md)를 따른다. 프로그램 선정·구현·설치·CAD 실행·제품 외부 API 시험은 수행하지 않았으며 M3 소스를 회수하거나 옮긴 패키지가 아니다. LICENSE는 소유자 결정 전 만들지 않는다.

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
