# 첫 코드 검토 결과

2026-11-16 KST. 작성자 시험과 독립 검토를 구분했다. 총괄은 실제 CLI demo와 전체52개(core25/native13/workflow14) 시험을 실행했고 native 실행기는 FreeCAD1.0.0이었다. 독립 workflow 검토자는 코드 수정 없이 실패를 재현하고 수정 후14개 workflow 시험과 원 재현 사례를 다시 확인했다.

발견·수정·재검증:
- 아주 작은 수의 접촉 판정 underflow: core의 정확 Fraction 기하 판정과 회귀 사례로 수정.
- worker 보고서 hardlink가 입력을 가리킬 경우 손상 가능: samefile 검사·원본 hash 보존 회귀로 수정.
- 손상된 session envelope가 CAD 실행 후 KeyError/TypeError: 필수 ID·history 및 선택/보호/범위 중복 필드의 일관성을 CAD 전 검증.
- NaN/Infinity 및 overflow JSON: 파싱 시 거부해 구조화된 invalid_json 반환.
- demo 게시 중 실패해 성공 report만 먼저 보일 수 있음: 완료 marker를 파일 이동 마지막으로 고정, 실패 주입으로 성공 report 미노출 검증.

수정 후 독립 검토의 원 실패 사례는 모두 CAD worker0회·원본 바이트 유지·새 성공 출력 없음으로 끝났다. --protect의 동일직경 전파 보호도 확인했다. 검토 범위의 추가 차단 결함은 없었다. 이것은 로컬 단일 사용자·명시 계획 범위의 검토이며 다인 인증·일반 STEP 추론·생산용 보안 보증이 아니다.
