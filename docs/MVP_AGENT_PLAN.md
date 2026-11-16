# 에이전트 활용과 인계 계획

2026-11-16 KST. 사용자의 실제 코딩 요청에 따라 실행했다. 에이전트는 사람의 제품 결정을 대신 확정하지 않으며 main 자동병합·유료 호출을 하지 않는다.

| 역할 | 배정·쓰기 경로 | 선행 입력 | 인계·검토 |
|---|---|---|---|
| 총괄/통합 | root, CLI·공용 문서·예제·CI·GitHub | 채팅·Obsidian·현재 Git | 계약 고정, 변경 충돌 관리, 실제 시험, 기능 branch와 draft PR |
| 공식자료 조사 | cad_research, 코드 수정 없음 | FreeCAD/SolveSpace 공식자료 | API·native·버전·라이선스의 근거와 한계; 제품 선정과 구분 |
| 데이터/보호 실행 | core_builder, model.py/policy.py/test_core.py만 | 새 맥락에서 인계·계약 읽기 | 스키마·원본 보존·선택 버전·보호 전파 시험 |
| native 실행 | native_builder, freecad_worker.py/test_native.py만 | 새 맥락에서 인계·계약 읽기 | 실제 FreeCAD 피처·제약·재열기·편집, 실패 증거 |
| 독립 검토 | 후속 reviewer, 우선 읽기·재현만 | 통합 결과와 실제 보고서 | 실패 경로·과장 주장·계약 불일치 검토; 수정은 총괄 통합 |

## 다른 맥락으로 전달한 방식
두 실행 에이전트는 기존 대화 이력을 받지 않고 시작했다. AGENTS, START_HERE_NEXT_CHAT, MVP_EXECUTION_CONTRACT, REQUIREMENTS를 읽고 목적·권한·비범위·출처 한계를 먼저 요약했다. 둘 다 known_plan_fixture, M3 미회수, STEP-only/외부 LLM/두 CAD 미검증, 해시 인증 아님, 쓰기 경계를 복구한 뒤 코딩에 착수했다. 이 확인은 새 맥락 인계가 사용됐다는 증거이며 새 ChatGPT 채팅방 생성 증거는 아니다.

일반 ChatGPT 새 대화를 직접 생성하는 연결 기능은 없다. 사용자가 다른 채팅을 열면 [START_HERE_NEXT_CHAT](START_HERE_NEXT_CHAT.md)의 시작 요청과 브랜치 URL을 전달하면 된다. 실제 인계 단위는 저장소+branch+commit+정본 문서+시험/제약이며 숨은 대화 기억이나 이 컨테이너 경로에 의존하지 않는다.

## 충돌·품질 관리
공용 파일은 총괄만 쓴다. 데이터 계약 변경은 소비 에이전트에게 먼저 전달한다. 새 작업은 allowed_paths와 기준 commit을 고정하며 충돌 시 상대 변경을 지우지 않는다. 이번 로컬 작업은 검증한 main snapshot의 분리 폴더이며 CLI clone은 인증 부재로 실패했다. 따라서 GitHub 도구의 branch/commit/PR 경로를 사용하고, 실제 clone이나 worktree가 있다고 표시하지 않는다.

각 결과는 수정 파일, 실행 명령, 실측 결과, 미실행, 실패, 다음 행동을 제출한다. 통합자는 단위 시험·실제 CAD·CI를 분리하고 필요한 실패를 직접 재현한다. 코드 작성자가 한 검사를 독립 검토로 세지 않는다. 무한 재시도·무승인 기능 대체·광범위 자동 변경은 허용하지 않는다.
