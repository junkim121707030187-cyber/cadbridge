# 상태와 근거
문서 버전 1.2.1 · 2026-11-16 KST

## 근거 범위
U: 이번 사용자 메시지의 최신 합의와 문서 작성 범위. H: 같은 메시지의 2026-10-12 M3 보존 자료 조사 요약. 이번 작업은 U/H를 제공 원문으로 사용했으며 링크의 보존 파일이나 원 M3 소스를 직접 회수·검사하지 않았다.

과거 근거 경로: [공유 기준 페이지](https://chatgpt.com/space/page_694d45239e2881918932e4c52f36e159), [총괄 대화](https://chatgpt.com/c/6acc8680-6bd4-83e8-b700-63ab162cf6f9). 링크의 존재는 이번 소스 확보·실행 증거가 아니다.

## M3 과거 기록(H), 이번 실행 아님
| 항목 | 보고된 범위·한계 |
|---|---|
| 입력 | XY 정렬 단일 사각 판재, 분리된 상부 사각 막힌 포켓, Z축 관통 홀 |
| 흐름 | 관측→공통 IR→후보→제한 선형 제약 풀이→형상 생성·검증→선택·누적 편집→STEP/IR/프로젝트 저장·재개 소스 묶음 존재 보고 |
| 편집 | 두께10→15mm, 홀 지름8→10mm, X간격60→70mm 사례 기록 |
| 시험 | 전체329 회귀와 별도87 검토는 합산 금지. 특정 실험 편집실행26/26, 의도일치18/26은 별도 지표이며 일반 CAD 성공률 아님 |
| 외부 LLM | API 연동 코드 보고, 실제 외부 새 모델 추론 기록상0회. 저장 후보를 반환한 로컬 HTTP/TLS 시험과 구분 |
| native | reader/writer 및 CATIA/SOLIDWORKS/NX 실제 피처 생성·저장·종료·재열기·편집 미구현·보류. 새 오픈소스 경로도 미검증 |
| workspace | 단일 사용자 로컬 프로젝트·편집 이력; Slack형 다인 공간이나 Git 분기/병합 아님 |
| 정책 차이 | propose→select와 달리 API run에 검증 후보 자동 선택 경로. 새 모호성 정책과 조정 필요 |
| 보호 | IR·참조·단위·연산 검사, 원본 보존, 미지원 거부, 마지막 유효 상태 보존, 출력 덮어쓰기 거부, 비밀 분리 보고 |
| 한도·인증 | 생성 최초1회+교정최대1회는 M3 구현값. 새 비용 정책 아님. approval/provenance 문자열·해시는 사용자 인증 아님 |
| 과거 제안 | 2026-09-24의 SW2022·12주·후보3개·120초는 현 확정값 아님 |
| 과거 수치 | 거리0.01mm·상대 대칭차부피1e-6은 새 제품 공차 아님 |

최소 시연 후보는 사각 판100×80×10mm, 중앙 포켓30×20×깊이5mm, Ø8 관통홀4개@(±30,±20)이다. 최종 검증 부품으로 확정하지 않았으며 원본 의도 추론 성능의 정답으로 부르지 않는다.

## 이번 산출물과 검토
문서·협업 설정·검사 도구와 해시 명세, 별도 복원용 JSON 1개 및 전달 ZIP을 생성했다. 문서 존재·UTF-8·상대 링크·요구 ID 참조·미정값 일관성·개인경로/비밀 패턴·과거/현재 상태 표현을 정적 검사하고 내용을 검토했다. manifest는 텍스트와 복원 JSON의 실제 SHA256을 기록하며 자기 자신과 ZIP은 제외한다. 자세한 검사 범위는 manifest의 review에 있다.

이번 수행 없음: 프로그램 구현·설치·CAD/API 테스트·M3 회수·회귀 재실행·외부 새 모델 추론·공개 게시. 저장소 업로드 상태는 아래를 따른다. 현재 native 관문과 제품 요구는 미검증이다. 다음 단계는 [작업 보드](TASK_BOARD.md)를 따른다.

## 1.1.0 협업 환경
참고 저장소를 읽고 협업 규칙·작업 카드·인계/검토 템플릿·모듈 계약 목록·문서 검사와 GitHub CI 정의를 추가했다. [참고 검토](REFERENCE_REVIEW.md)에 확인 commit과 읽은 범위가 있다. 코드 검토 협업과 CAD 제품의 다인 workspace 구현은 별개다.

문서 검사 도구는 이번 작업 환경 준비용이며 CAD 프로그램 구현이 아니다. Python 검사 실제 결과·해시·파일 수는 [BUNDLE_MANIFEST](../BUNDLE_MANIFEST.json)와 [WORKSPACE_REVIEW](WORKSPACE_REVIEW.md)에 기록한다. GitHub CI는 원격 실행 결과가 확인되기 전 ‘실행 미확인’이다.

당시 저장소 상태: 사용자가 브라우저 작업 중단 및 직접 업로드할 파일 제공을 요청해 자동 생성·업로드를 중단했다. 이후 원격 재개 상태는 아래 1.2.1 기록을 따른다. CAD/API 실행·설치·M3 소스 회수 없음.

## 1.2.0 개념도와 직접 업로드 패키지
[제품 개념도](PRODUCT_CONCEPT.md)에 합의·제안·미정을 표시하고 후속 결정이 필요한 항목을 모았다. README에서 개념도로 연결하고 최신 작업 범위로 결정·인계·작업 보드를 갱신했다. 복원 JSON·manifest·ZIP을 새로 만들고 문서 및 바이트 일치를 검사한다. 실제 검사 결과는 manifest의 review를 따른다.

GitHub 도구 확인: 2026-11-16 계정 조회 성공, 접근 가능한 설치 저장소의 cadbridge 검색 결과 0개. 도구 목록에서 파일·커밋·브랜치·PR 기능과 저장소 생성 기능 부재를 확인했다. 저장소 전체가 없다고 단정하지 않으며 파일 쓰기·커밋·브랜치·PR 생성은 실행하지 않았다. 이 확인은 CADBridge 제품의 외부 API 시험이 아니다.

## 1.2.1 지정 GitHub 저장소에 초기 반영
사용자가 [cadbridge](https://github.com/junkim121707030187-cyber/cadbridge)를 직접 지정하고 업로드를 재요청했다. GitHub 도구로 비공개 저장소·main·쓰기 권한과 초기 README 한 줄을 확인했다. 기준 커밋 `5cc1f40aac88795ae5cb57abe3471e1b8c030e3c`를 부모로 보존한 [초기 반영 커밋 b5ccbe0](https://github.com/junkim121707030187-cyber/cadbridge/commit/b5ccbe09dfc3cf4545f86cbe7f4aeef23551836b)에 문서·개념도·협업 설정·검사 도구 33개를 루트에 올렸다. main ref를 재조회해 반영을 확인했고 원격 트리 33개 blob 해시를 로컬 바이트와 모두 대조했다. 제품 개념도는 같은 커밋에서 다시 읽어 내용 일치를 확인했다.

로컬 검사: 정적 문서 검사와 manifest 32개 파일의 SHA256·크기 대조 통과. 이 기록 갱신도 같은 검사 후 별도 문서 커밋으로 반영한다. 초기 반영 커밋의 [GitHub 문서 검사 실행 43802258010](https://github.com/junkim121707030187-cyber/cadbridge/actions/runs/43802258010)은 completed/success로 확인했다. 이 결과는 해당 초기 커밋의 문서 CI 결과이며 CAD/API 제품 검증이 아니다. 후속 커밋은 Actions에서 해당 SHA의 결과를 확인한다. Mermaid 원문은 반영했으며 브라우저에서 그림을 시각 검토하지는 않았다.

기존 1.2.0 ZIP과 체크포인트는 보존한다. 원격에 전달하는 것은 개발 준비 정본이며 M3 실행 소스나 CAD 구현은 포함하지 않는다. 원격 GitHub 쓰기 재개는 이 저장소의 준비 파일 업로드에 한정하며 브라우저 로그인은 재개하지 않는다.


## 2026-11-16 · 로컬 통합 시제품 추가

`prototype/`에 M3 관측과 Terra 후보·native 모델 생성/편집, 로컬 파일·형상 워크스페이스를 추가했습니다. AI 예제는 합성 CB-P01 하나의 실제 두 저장 버전입니다. 기존 개발 PC에서의 65개 소프트웨어 검사 함수·194개 하위 사례와 native 실행 기록은 `prototype/evidence/`에 보존했습니다. 이번에는 사용자 요청으로 새 실행 확인을 미루고 업로드만 수행합니다. 다른 PC 설치·원격 다인 협업·최종 제품 합격을 새로 통과 처리하지 않습니다. [배포 범위와 후속 작업](PROTOTYPE_UPLOAD_2026-11-16.md)을 참고합니다.

## 2026-11-23 · 줄바꿈 정책 변경 (CB-010 1단계)

현상: clone 직후 33개 파일이 수정됨(M)으로 표시됐다. 작업 폴더 바이트는 33개 모두 커밋 blob과 같았다. 원인은 `18edd4a`에 CRLF로 저장된 파일과 당시 `.gitattributes`의 `eol=lf` 규칙의 충돌이다. 33개 중 26개는 `prototype/` 안에 있으며, 그 SHA256이 `session.json` 등 실행 기록과 `prototype/source-provenance/integrated-manifest.json`에 기록되어 있다. integrated-manifest의 122개 항목은 모두 현재 바이트와 일치했다. 시제품 앱(`prototype/app/cadbridge/workflow.py`의 `load_session`)은 프로젝트를 열 때 이 해시를 검사하므로 이 파일들의 바이트를 바꾸지 않았다.

변경(구현): `.gitattributes`를 `* -text`로 바꿔 Git이 어느 OS에서도 줄바꿈을 변환하지 않게 했다. `.editorconfig`는 LF를 유지하고 실행·출처 기록 경로만 예외로 뒀다. 결정은 [결정 로그](DECISIONS.md) D-12, 작업 범위는 [CB-010](tasks/CB-010.md)를 따른다.

로컬 검증(2026-11-23, git 2.43.0, Python 3.12.3, 기준 commit `18edd4a`, 미커밋 작업 폴더):
- `git status`: 기존 33개 M 표시 해소. 수정 허용 경로 10개만 표시
- 바이트 대조(`git hash-object --no-filters`와 index blob 비교): 수정 허용 경로 밖 tracked 파일 변경 0
- 임시 clone 모의: 새 규칙에서 `git add`한 blob이 작업 폴더 바이트와 같음. 기존 규칙에서는 CRLF 파일이 LF로 바뀌어 저장됨
- `python scripts/check_workspace.py`: pass, 오류 0 (files 160, text_files 125, relative_links 146)
- `python scripts/check_workspace.py --verify-manifest`: fail 131건. 기준 상태와 같은 크기 필드명(`bytes`) 오류만 남고 새 오류 0. 2단계에서 다룬다

미실행: GitHub CI(사용자 커밋 후 해당 SHA에서 확인), Windows checkout 확인, 편집기의 `.editorconfig` 예외 적용 확인(검사 도구 없음), CAD/API 실행. 커밋·push는 사용자가 직접 한다.

## 2026-11-23 · 매니페스트 크기 필드명 통일 (CB-010 2단계)

1단계는 PR #3으로 main에 병합됐다(병합 커밋 `7ace128`). 병합 커밋의 GitHub CI 결과는 이 기록에서 확인하지 않았다.

변경(구현): `BUNDLE_MANIFEST.json`의 파일 항목 131개가 크기를 `bytes`로 적고 있어, `size_bytes`를 읽는 검사기가 크기 불일치로 실패했다. 이 131개 항목의 이름을 `size_bytes`로 바꾸고 키 순서를 나머지 항목과 같은 `path`, `sha256`, `size_bytes`로 맞췄다. SHA256과 크기 값은 바꾸지 않았다. 함께 수정한 문서 4개의 해시·크기만 새로 계산했다. 머리말(`document_version`, `review` 등)은 갱신하지 않았다.

로컬 검증(2026-11-23, git 2.43.0, Python 3.12.3, 기준 commit `7ace128`, 미커밋 작업 폴더):
- 이름을 바꾼 131개 항목의 SHA256·크기 값이 변경 전과 같음
- `python scripts/check_workspace.py --verify-manifest`: pass, 오류 0 (manifest_entries 159). 변경 전 오류 131건
- `python scripts/check_workspace.py`: pass, 오류 0
- 수정 허용 경로 밖 tracked 파일 바이트 변경 0

미실행: GitHub CI(커밋 후 확인), CAD/API 실행.
