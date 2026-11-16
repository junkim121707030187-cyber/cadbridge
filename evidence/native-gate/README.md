# 실제 native 기술실험 증거

2026-11-16 KST, Linux, FreeCAD1.0.0. 첫 코드의 알려진 계획 예제군이며 STEP-only 추론이나 외부 LLM 호출이 아니다. product_acceptance=not_assessed다.

- fixture.step/fixture-plan.json: 독립 Part 커널로 만든 기준 STEP과 명시 계획.
- initial/model.FCStd: 실제 Body/PlateSketch/Pad/PocketSketch/Pocket/HolesSketch/Holes, 저장·close·reopen 및 새 프로세스 inspect.
- edited/model.FCStd: 기존 동일 피처를 두께10→15mm, 네 홀8→10mm로 편집·재저장·새 프로세스 inspect. 판100×80mm·포켓30×20×깊이5mm·홀 중심(±30,±20) 유지.
- 각 session.json: 이전 버전 연결, 선택 계획 SHA, 입력/출력 해시, 보호 조건, 편집 이력·가정·검증 범위.
- build-report.json/inspect-report.json: 실제 피처 타입·치수·제약·기하 대조. 스케치3개 각각12제약, 모두 완전구속. 기준/편집 후 독립 형상과 대칭차 부피 모두0mm³.
- demo-report.json: 두 버전과 실제 편집 결과. 기준 부피74989.38070170252mm³, 편집 부피112287.61101961532mm³.

재현은 저장소 루트에서 `python -B -m cadbridge demo --output ../새폴더`다. 실행기가 없는 CI의 native skip은 이 실제 실행 증거를 대체하지 않는다. 최종 제품 공차·두 CAD 이전·권한 인증·AI 의도 추론은 별도 검증해야 한다.
