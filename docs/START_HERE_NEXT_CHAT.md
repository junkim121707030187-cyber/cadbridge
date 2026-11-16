# CADBridge 다음 채팅 시작점

## 이어받을 현재 상태
MVP0.1 첫 코드와 [시연 근거](../evidence/native-gate/README.md)가 있다. 실제 FreeCAD1.0.0에서 전체52개 시험(core25/native13/workflow14)과 CLI 시연을 수행했다. 두께10→15mm, 동일직경 홀4개8→10mm, 스케치3개 각각12제약 및 완전구속, 원본보존·별도프로세스재열기를 확인했다. code source는 cadbridge/, tests/, examples/다. 다음 작업은 CB-007이며 제품 전체 MVP/STEP-only/LLM/G2 완료는 아니다. 재현 명령은 [MVP_QUICKSTART](MVP_QUICKSTART.md)에 있다. feature branch 최신 commit과 PR/Actions 상태를 조회하고 계속한다.

이 문서는 원래 대화를 볼 수 없는 새 실행 에이전트와 다음 ChatGPT 채팅을 위한 인계다. 다른 ChatGPT 대화가 자동 생성됐다는 뜻은 아니다. 새 실행 에이전트는 이 문서와 아래 정본을 먼저 읽고 코딩한다.

## 복사할 시작 요청
> 비공개 https://github.com/junkim121707030187-cyber/cadbridge 의 feat/cb-002-native-foundation 브랜치를 확인하세요. AGENTS.md, docs/START_HERE_NEXT_CHAT.md, docs/MVP_PLAN.md, docs/MVP_AGENT_PLAN.md, docs/MVP_EXECUTION_CONTRACT.md, docs/STATUS_AND_EVIDENCE.md, docs/TASK_BOARD.md를 읽고 현재 commit·변경·시험 상태를 확인한 뒤 배정된 다음 카드를 이어가세요. 이 문서가 기존 채팅의 결정·근거·권한·한계와 재현 경로를 전달합니다. 확인되지 않은 과거 시험을 재실행 결과로 주장하거나 main을 자동 병합하지 마세요.

## 제품 맥락
기계 설계 협업자가 STEP을 받으면 형상은 남아도 피처·제약·수정 의도가 소실된다. 목표는 편집 가능한 native 모델과 변경 맥락을 전달하는 것이다. 첫 단계 STEP→오픈소스 native, 다음은 서로 다른 독립 CAD A→B에서 수신·수정·저장. 왕복·동시 편집·병합·상용 CAD·조립체는 첫 완료 범위 밖이다.

보호 조건은 시작 시 받는다. 모호성은 후보 근거와 편집 차이를 보여주고 선택 전 보류한다. 기능 대체는 허용 범위 안에서 공개한다. 원본확인·기하측정·사용자요구·AI가정을 구분한다. 기하 일치와 native 편집·의도·권한·컨텍스트 판정을 분리한다. 해시는 인증이 아니며 원시 대화 전체나 비공개 내부 추론은 저장하지 않는다.

## 기준·권한·자료
- 정본 기준: main fe42a66e8bcbb88566f2ff482cbaecb9bea4d784, 준비 파일 33개 및 문서 CI 통과. 참고 void_hackathon은 수정 금지.
- 최신 사용자 요청: 채팅·Obsidian·Git을 참고해 MVP 작업계획과 에이전트 활용계획, 다른 채팅용 맥락 전달, 코딩 시작. 따라서 과거 문서 전용/native 보류는 이번 첫 구현 범위에 한해 대체됐다. 분리 기능 브랜치·draft PR, 로컬 CAD 실행과 검증은 허용. main 자동병합·유료 호출·공개 전환은 허용되지 않았다.
- Obsidian: brain/wiki/index.md → brain/wiki/maps/projects.md를 읽고, 루트 'CADBridge 팀 인수인계와 구현 결과.md'(2026-10-12)를 확인했다. 복사본도 대조했다. 과거 문서의 native 보류와 API 우선순위는 당시 상태다. 최신 제품 요구를 조용히 대체하지 않는다.
- M3: 제한 사각판/상부 포켓/Z관통홀, API 코드·329회귀 및 별도87검토는 보고된 과거 기록이다. 26/26 편집 실행과18/26 의도일치는 다른 지표다. M3 원본 소스는 이번에 미회수. 신규코드를 M3 이식·재현으로 부르지 않는다.
- FreeCAD1.0.0/freecadcmd 실행 및 PartDesign::Body 생성 확인. 전체 native 관문은 구현 후 실제 증거로 판정한다. CadQuery/OCP는 설치돼 있지만 독립 CAD 프로그램 두 개로 세지 않는다. SolveSpace는 후속 CAD 후보이며 미설치·미실행이다.
- 일반 git clone은 CLI 자격증명 부재로 실패했다. 로컬은 검증한 main 파일의 분리 snapshot이며 GitHub 도구로 기능 branch에 반영한다. 실패를 GitHub 도구 권한 부재로 해석하지 않는다.

## 지금 작성할 것과 한계
공통계약의 known_plan_fixture만 첫 코드로 다룬다. 명시 계획+STEP 기하 대조→실제 FreeCAD 스케치/피처→저장/별도 프로세스 재열기→치수 변경→재계산/재저장. 이것은 STEP-only 의도 추론·외부 LLM 성능·두 CAD G2 통과가 아니다. 최종 CAD쌍·제조 공차·권한 인증·대체 UI·비용정책·유지보수는 계속 미정이다. 최종 제품 합격은 not_assessed다.

작업 분담과 상태·재현 명령·후속 카드·구체 근거는 MVP_PLAN, MVP_AGENT_PLAN, TASK_BOARD, STATUS_AND_EVIDENCE에서 갱신한다. 이 문서와 정본으로 새 에이전트의 독립 읽기·요약 및 코딩 착수를 확인한다.
