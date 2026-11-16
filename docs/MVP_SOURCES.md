# MVP 출처 대조

2026-11-16 KST. 원문 전체 대화나 비공개 내부 추론은 복사하지 않고 구현 판단에 필요한 결정·관측만 남긴다.

| 출처 | 읽은 근거와 현재 사용 |
|---|---|
| 현재 채팅 | STEP→native, 다음 서로 다른 CAD A→B, 보호 조건·모호성 선택·컨텍스트 보존, 준비 후 최신 MVP 코딩 승인 |
| GitHub main | fe42a66e8bcbb88566f2ff482cbaecb9bea4d784. AGENTS/README/요구/검증/개념도/인계 등 준비 정본 33개. 현재 branch가 달라지지 않음을 조회 |
| Obsidian 입구 | brain/wiki/index.md SHA256 956fc0652959d17b9b4a16ee7261d1159b795c8bb994e03b727bf403f113fbee, projects 지도 SHA256 7b886aec9560ed6c85416d52e241c2365e57b0161dec498a469a9b72c884942b |
| Obsidian 과거 인계 | 루트 CADBridge 팀 인수인계와 구현 결과.md SHA256 64045c05ff0eff95367a43567bc2b63fcea1fe67a88736b0e20b06a9f3d15483, 192줄을 읽음. 3-2/캡스톤_심화실습/받은자료_2026-10-29/의 동명 복사본도 읽음. M3 시험/파일 위치는 보고 정보이며 소스 회수 증거가 아님 |
| 실행 환경 | freecadcmd --version: FreeCAD1.0.0. 해당 실행기로 PartDesign::Body 실제 생성. OCP/CadQuery 존재, SolveSpace 실행기 없음. 시스템 Python 직접 import는 Mod 경로 부족으로 실패했지만 freecadcmd 경로는 동작 |

과거 인계 문서의 10월 native 보류·API 우선순위와 최신 구현 요청을 구분한다. 과거 329회귀·별도87검토·26/26편집·18/26의도일치를 합산하거나 새 결과로 쓰지 않는다. M3 전달 ZIP/원본은 미회수이므로 이 branch는 새 구현이며 이전 소스를 덮어쓰지 않는다.

## 공식 기술 근거
- [FreeCAD headless 실행](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Headless_FreeCAD.md)
- [FreeCAD Sketcher scripting](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_scripting.md)
- [FreeCAD PartDesign Pad](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Pad.md)
- [FreeCAD PartDesign Pocket](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_Pocket.md)
- [FreeCAD native FCStd](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/File_Format_FCStd.md)
- [SolveSpace reference](https://solvespace.com/ref.pl): 독립 parametric CAD, 제약·extrude와 STEP 내보내기. STEP 경유 후속 A 후보 |
- [SolveSpace 다운로드](https://solvespace.com/download.pl): 조사 시 3.3 stable/2026-10-20. 현재 환경 설치·실행은 안 함 |
- [SolveSpace 공식 README](https://github.com/solvespace/solvespace/blob/master/README.md): CLI 빌드와 라이선스. CLI를 native 생성 API로 오인하지 않음 |

공식 문서의 최신 내용과 설치된 FreeCAD1.0.0은 다를 수 있으므로 속성·함수는 실제 실행으로 검증한다. FreeCAD LGPL 계열/SolveSpace GPLv3는 도구 조사 사실이며 CADBridge 자체 LICENSE를 새로 부여하지 않는다.
