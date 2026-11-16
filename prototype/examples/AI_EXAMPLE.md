# AI 작업 예제 · CB-P01 플레이트

이 예제는 합성 시험 부품 **한 개**를 STEP 기하 관측 → Terra 구조화된 설계 후보 → 검사 → FreeCAD native 스케치·Pad·Pocket으로 재구성한 기록입니다. 실제 팀 부품이나 범용 복원 성능을 대표하지 않습니다.

## 입력과 AI 결과

- [입력 STEP](input.step)
- [기하 관측·요구 입력](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/agent-request.json)
- [Terra 구조화된 응답](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/executed-agent-response.json)
- [Terra 실행 메타데이터](terra-execution.json): `gpt-6.1-terra`, `codex_cli`, 반환 코드 0, 시작·완료 시각 및 요청·응답 해시. 비공개 내부 추론과 계정 설정은 포함하지 않습니다.
- [실행·생성 근거 요약](../evidence/validation.json)

## 두 저장 버전 비교

| 항목 | v001 · 재구성 | v002 · 치수 수정 |
|---|---|---|
| 판재 크기 | 100 × 80 × 10 mm | 100 × 80 × 15 mm |
| 중앙 포켓 | 30 × 20 mm, 깊이 5 mm | 동일 |
| 관통 홀 | 4개, Ø8 mm | 4개, Ø10 mm |
| 홀 X 간격 | 60 mm | 70 mm |
| 유지 조건 | 홀 동일 지름·중심 대칭·관통, 포켓 윗면 기준 | 동일 |

v002는 AI가 만든 최초 후보를 기반으로 치수를 수정한 결과입니다. 모든 편집 시점마다 새 LLM 추론을 했다는 뜻은 아닙니다.

| 버전 | 편집 가능한 native 파일 | 교환 파일 | 기하 검사 |
|---|---|---|---|
| v001 | [FreeCAD](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v001/model.FCStd) | [STEP](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v001/result.step) | [검사 기록](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v001/geometry-check.json) |
| v002 | [FreeCAD](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v002/model.FCStd) | [STEP](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v002/result.step) | [검사 기록](../data/projects/3e021549-36ac-45b6-87d2-2df611ec475b/versions/v002/geometry-check.json) |

GUI에서 바로 열어 살펴볼 수 있도록 별도 표시 상태를 저장한 [편집 결과 FreeCAD 파일](../evidence/CADBridge_편집결과.FCStd)과 [STEP 결과](../evidence/CADBridge_편집결과.step)도 동봉했습니다. `versions`의 원본 저장 파일은 그대로 보존했습니다.

워크스페이스에서는 **설계-검토 → 형상 → CB-P01 플레이트**를 선택하고 버전을 바꿉니다. 모델 도구에서는 이 프로젝트를 열어 저장 결과와 치수를 확인합니다. **다른 PC에서의 재현 실행은 이번 업로드에서 확인하지 않았습니다.**
