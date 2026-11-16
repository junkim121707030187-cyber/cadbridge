# CADBridge 개발 준비 정본
MVP 0.1 코드 · 문서 버전 2.0.0 · 2026-11-16 KST

서로 다른 CAD 프로그램·버전을 사용하는 기업체와 팀이 설계와 변경 이력을 공유하고 이어서 편집하는 협업 워크스페이스를 목표로 한다. 첫 단계는 STEP에서 편집 가능한 오픈소스 CAD native 부품을 재구성하는 것이다. 이후 서로 다른 오픈소스 CAD 프로그램 사이로 설계 맥락과 제약을 이전한다.

현재 기능 브랜치에는 명시 계획+STEP 기하 대조로 실제 FreeCAD 스케치·제약·Pad/Pocket을 만들고 저장·별도 프로세스 재열기·치수 편집·재저장하는 첫 코드가 있다. Linux/FreeCAD1.0.0에서 52개 시험과 알려진 계획의 시연을 통과했다. STEP-only 의도 추론·외부 LLM·서로 다른 두 CAD 이전은 아직 구현·검증하지 않았으며 최종 제품 합격은 not_assessed다. 과거 M3 소스를 이식한 코드가 아니다. [실제 결과](docs/STATUS_AND_EVIDENCE.md)와 [실행 안내](docs/MVP_QUICKSTART.md)를 읽는다. LICENSE는 소유자 결정 전 만들지 않는다.

## MVP 작업과 이어받기
[작업 계획](docs/MVP_PLAN.md) · [에이전트 활용 계획](docs/MVP_AGENT_PLAN.md) · [다른 채팅 시작 문서](docs/START_HERE_NEXT_CHAT.md) · [기계 판독 맥락](docs/MVP_CONTEXT.json) · [출처 대조](docs/MVP_SOURCES.md).

```bash
python -B -m unittest discover -s tests -v
python -B -m cadbridge demo --output ../cadbridge-demo
```

원본과 이전 버전을 덮어쓰지 않는 새 출력 경로를 사용한다. [재현 가능한 시연 자료](evidence/native-gate/README.md)에는 수정 전후 FCStd·STEP·프로젝트 컨텍스트·관측 보고서를 포함했다. main은 준비 정본을 유지하고 구현은 feat/cb-002-native-foundation에서 draft PR로 검토한다.

## 읽는 순서
1. [제품 개념도와 미정 사항](docs/PRODUCT_CONCEPT.md), [제품 개요](docs/PROJECT_BRIEF.md)와 [요구사항](docs/REQUIREMENTS.md)
2. [결정 로그](docs/DECISIONS.md)와 [현재 상태·근거](docs/STATUS_AND_EVIDENCE.md)
3. [구조 제안](docs/ARCHITECTURE.md), [데이터·컨텍스트](docs/DATA_AND_CONTEXT.md), [AI 정책](docs/AI_POLICY.md)
4. [검증 관문](docs/VALIDATION.md), [개발 절차](docs/DEVELOPMENT_WORKFLOW.md), [작업 보드](docs/TASK_BOARD.md)
5. 작업 전 [AGENTS](AGENTS.md), 인계 시 [HANDOFF](docs/HANDOFF.md)

## 패키지 사용
ZIP을 풀고 cadbridge-seed/ 안의 파일과 폴더를 사용자가 만든 Git 저장소 루트에 복사하거나 업로드한다. 기존 파일과 충돌하면 비교 후 반영한다. cadbridge-seed 폴더 자체를 이중 중첩하지 않는다. 전달 ZIP에는 이 폴더와 별도 seed-docs.json이 들어 있다. JSON은 업로드 필수 파일이 아닌 복원용 사본이며 manifest와 archive를 제외한 정본 텍스트 파일을 보존한다. 복원 시 path를 상대 경로로 한정하고 절대경로·상위 경로 탈출·중복 경로를 거부한 뒤 UTF-8로 저장한다. GitHub에서는 PRODUCT_CONCEPT.md의 Mermaid 개념도를 볼 수 있다.

[BUNDLE_MANIFEST.json](BUNDLE_MANIFEST.json)의 files에는 현재 저장소 파일·보존 증거의 SHA256을 기록한다. `python -B scripts/check_workspace.py --verify-manifest`로 별도 복원 JSON 없이 검증한다. 과거1.2.0 ZIP/복원 JSON은 당시 체크포인트이며 이 구현 브랜치의 새 코드까지 포함한 전달본은 아니다. manifest 자신은 순환 해시를 피하기 위해 제외한다. 파일 해시는 무결성 확인용이며 승인·신원 인증 수단이 아니다.

## 협업 환경 시작
[CONTRIBUTING](CONTRIBUTING.md)에서 사람용 절차를 읽고 [에이전트 작업 절차](docs/AGENT_WORKFLOW.md), [계약 목록](docs/INTERFACES.md), [작업 카드](docs/tasks/README.md)를 사용한다. [참고 저장소 검토](docs/REFERENCE_REVIEW.md)에 적용·제외 근거가 있다.

문서 검사: `python -B scripts/check_workspace.py --verify-manifest` (Python3.11 이상, 추가 설치 없음). GitHub CI는 문서·단위 시험을 수행하고 FreeCAD가 없으면 native 시험을 명시적으로 skip한다. 실제 CAD 실행은 이 작업 환경의 별도 증거로 남겼다. 외부 모델 호출·자동 배포·자동 merge는 없다. 다음 작업은 [작업 보드](docs/TASK_BOARD.md)의 CB-007이다.
