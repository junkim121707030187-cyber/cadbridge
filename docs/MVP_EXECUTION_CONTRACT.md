# MVP 0.1 실행 계약

기준 commit: fe42a66e8bcbb88566f2ff482cbaecb9bea4d784. 저장소: https://github.com/junkim121707030187-cyber/cadbridge. 작업 branch: feat/cb-002-native-foundation. 최신 사용자는 계획·인계와 코딩 시작을 승인했다. 과거 문서 전용 범위와 native 보류를 이번 첫 구현 범위에 한해 대체한다.

## 목적과 비범위
이번 첫 슬라이스는 명시된 계획으로 제한 STEP을 FreeCAD의 실제 Sketcher/PartDesign 피처로 재구성하고 저장·별도 프로세스 재열기·치수 편집·재계산·재저장을 검증한다. 제공 계획을 사용하는 known_plan_fixture 군이다. STEP에서 원래 의도를 추론했다거나 외부 LLM을 호출했다고 표시하지 않는다. STEP-only 자동 추론과 두 CAD 간 G2 완료는 후속 작업이다. Solvespace는 후속 독립 CAD 후보일 뿐 현재 실행하지 않았다. M3 원본 소스는 회수하지 않았고 신규 구현을 M3 이식이라고 부르지 않는다.

## 파일 경계
- core 실행 에이전트: cadbridge/model.py, cadbridge/policy.py, tests/test_core.py.
- native 실행 에이전트: cadbridge/freecad_worker.py, tests/test_native.py.
- 총괄: 나머지 CLI·문서·예제·CI·통합·GitHub. 공용 파일 동시 수정 금지.

## 공통 계획 v1
JSON: schema='cadbridge.plan.v1', units='mm', plate={width,height,thickness}, pocket=null 또는 {width,height,depth}, holes=[{x,y,diameter}], hole_relation='equal_diameter' 또는 'independent'. 모든 수치는 bool 아닌 유한 양수(좌표는 유한 실수), 판 중심 XY=0, 바닥 Z=0. 포켓은 중심 정렬, 깊이<thickness, 폭/높이<판, 홀은 Z관통. 홀끼리/포켓과 겹침·접촉 및 판 경계 접촉을 거부한다. 이 슬라이스는 최대 홀 16개, 추가 키와 미지원 schema/units를 거부한다.

core API:
- BridgeError(code, message): .code 속성을 가진 ValueError 하위.
- validate_plan(data:dict)->dict: 검증 후 deepcopy 정규형. 수치 float, 순서 보존. 동일 직경 관계의 불일치 거부.
- plan_sha256(plan:dict)->str: 정규형 JSON(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)의 UTF-8 SHA256.
- apply_edit(plan, changes:dict, protected_fields:list[str])->dict: plate.width/height/thickness, pocket.width/height/depth, holes.N.x/y/diameter만 허용. equal_diameter에서 한 홀 diameter 편집은 전부 전파한다. 실제 변경된 모든 필드에 보호 검사(전파 포함), 원본 무변경. 미지원·빈 편집·모순 편집·구조 변경 거부.
- require_selection(plan:dict, selected_sha:str|None)->str (policy.py): canonical plan hash와 명시적 선택 일치 필요. 해시는 계획 버전 결속이며 사용자 인증이 아니다. 로컬 단일 사용자만 지원, 다인 인증 R-12 통과 주장 금지.

## FreeCAD worker 실행 계약
freecadcmd에 이 .py를 고정 스크립트로 실행한다. 환경 CADBRIDGE_REQUEST에 요청 JSON 절대경로를 넣는다. 임의 코드 실행·eval 금지. worker는 request.report_path에 결과 JSON을 기록하며 실패도 status='error', code/message를 기록한다. CLI는 프로세스 returncode만 믿지 않고 report 상태를 확인한다. 독립 worker는 core 모듈 의존 없이 이 계약 JSON을 소비한다.

요청: action='fixture'|'reconstruct'|'edit'|'inspect', plan=정규형, 필요 시 previous_plan, input_step, input_native, output_native, output_step, report_path. 부울 비교 허용치는 request.volume_tolerance_mm3(기본 1e-5). 출력 경로/원본/덮어쓰기 차단과 staging은 총괄 CLI가 담당하되 worker도 기존 output_native/output_step을 덮어쓰지 않는다.

- fixture: Part 커널로 명시 계획의 STEP 생성. 재구성과 다른 생성 경로, 결과에 known_plan_fixture 명시.
- reconstruct: input_step 읽기·단일 유효 solid 검증. 실제 Sketcher/PartDesign Body/Pad/Pocket native 생성. 생성물과 STEP의 양방향 cut 합 부피로 비교; 초과 시 실패. 단순 imported Part::Feature로 대체 금지. native 저장·close·open 후 상태를 관측한다.
- edit: input_native를 열고 기존 피처·스케치 치수 값을 new plan으로 변경(재구성으로 대체 금지), 재계산·저장·close·reopen. 원본 유지. previous_plan 및 native 메타데이터 일치 검사. 변경된 형상은 계획으로 만든 독립 Part 커널 형상과 비교한다.
- inspect: input_native의 피처·스케치·제약 수·형상·저장된 계획을 관측한다.

성공 report: status='ok', action, freecad_version, input_information_group='known_plan_fixture', volume_mm3, symmetric_difference_mm3(해당 시), native_features=[{name,type}], sketch_constraints={sketch_name:count}, reopened=true(해당 시), plan=정규형. close→reopen은 worker 내 수행하되 CLI는 inspect를 새 worker 프로세스에서도 실행해 지속성을 확인한다. Shape 유효성·단일solid·스케치/피처 타입·실제 치수 변경을 검사한다.

## 검증 범위
기술검증 프로파일의 부피 허용치 1e-5 mm³는 엔지니어가 고정한 탐색 시험 기준이며 제조 공차나 최종 합의 공차가 아니다. 결과 product_acceptance='not_assessed' 유지. 실패 시 새 결과를 성공 버전으로 승격하지 않고 입력·마지막 유효 상태 보존. 핵심 정책 시험과 실제 FreeCAD 통합 시험을 분리한다. 없는 FreeCAD 환경에서 integration을 skip할 때 그 이유를 출력한다.
