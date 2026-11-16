# 첫 코드 실행

Python3.11 이상, 실제 native 작업에는 FreeCAD console 실행기가 필요하다. Python 의존성은 표준 라이브러리뿐이며 저장소 루트에서 실행한다. FreeCAD의 Python 버전은 부모 Python과 달라도 된다. CLI가 별도 프로세스로 호출하며 코드 생성이나 eval은 사용하지 않는다.

```bash
python -B -m cadbridge doctor
python -B -m cadbridge plan-inspect examples/plate-pocket-holes.plan.json
python -B -m unittest discover -s tests -v
python -B -m cadbridge demo --output ../cadbridge-demo
```

FreeCAD 실행기를 찾지 못하면 CADBRIDGE_FREECADCMD 환경변수에 실제 FreeCADCmd 실행기 경로를 지정하거나 `python -B -m cadbridge --freecadcmd 경로 demo --output 새폴더`를 사용한다. Windows용 실행기와 경로의 실제 실행은 아직 검증하지 않았다. 현재 환경은 Linux/FreeCAD1.0.0이다.

demo는 알려진 계획으로 독립 Part 커널 STEP을 만든 뒤 실제 스케치·피처 재구성과 형상 대조, 저장·새 프로세스 재열기, 두께10→15mm와 네 홀8→10mm 편집·재저장을 수행한다. initial/edited 각각의 native model.FCStd, 결과 STEP, session.json, build/inspect 보고서를 만든다. 출력은 반드시 없는 새 폴더다. 저장된 원본 계획·STEP·native는 후속 편집으로 덮어쓰지 않는다. 이 실행은 STEP 의도 추론이나 외부 LLM 호출이 아니다.

## 개별 단계
1. plan-inspect로 계획의 SHA256을 확인한다. 이는 계획 버전 선택값이며 인증 토큰이 아니다.
2. 해당 계획에 맞는 STEP을 지정해 reconstruct를 실행한다.

```bash
python -B -m cadbridge reconstruct --input input.step --plan examples/plate-pocket-holes.plan.json --selected-plan-sha 확인한해시 --protect plate.width --protect plate.height --output ../cadbridge-project
python -B -m cadbridge inspect ../cadbridge-project
```

3. session.json의 version_id를 확인하고 명시적으로 기대 버전을 지정해 편집한다.

```bash
python -B -m cadbridge edit --project ../cadbridge-project --changes examples/thickness-and-holes.edit.json --expected-version 확인한버전 --output ../cadbridge-edited
```

선택 해시·기대 버전·파일 해시 불일치, 보호 조건 위반, 기존 출력, STEP 형상 불일치, 미지원 입력은 거부한다. 실패한 CAD 작업의 보고서는 고유 staging 폴더에 남으며 성공 session으로 게시하지 않는다. inspect는 프로젝트 파일/계획 해시를 확인하는 CLI이고 실제 native 재열기는 생성·편집 워크플로에서 새 FreeCAD 프로세스로 수행한다.

최종 제품 공차·다인 인증·모델 공급자·두 CAD 이전은 미검증이다. 보고서의 engineering_exploration과 product_acceptance=not_assessed를 그대로 해석한다. [작업 계획](MVP_PLAN.md)과 [상태·근거](STATUS_AND_EVIDENCE.md)에서 실제 수행 결과를 확인한다.
