# 사람과 에이전트의 협업 시작
[README](README.md) · [공통 작업 규칙](AGENTS.md) · [에이전트 절차](docs/AGENT_WORKFLOW.md)

이 기준선은 CADBridge 문서와 협업 준비 도구다. CAD 프로그램·패키지를 설치하지 않으며 CAD/API 제품 시험은 아직 없다. 참고 저장소의 웹앱 스택과 해커톤 일정은 가져오지 않았다.

## 처음 할 일
1. 정본 문서와 현재 작업 카드, 결정 로그를 읽고 이번 작업의 요구 ID와 범위를 확인한다.
2. 사용할 Git 저장소를 확인하고 `git status --short --branch`로 사용자 변경과 기준 branch를 확인한다. Git 명령은 저장소 루트에서 실행한다.
3. 작업 카드를 배정받는다. 한 작업의 수정 경로와 검토자를 정한 뒤 작업별 branch를 사용한다. 병렬 작업은 서로 다른 worktree(분리 작업 폴더)를 우선한다.
4. 검사에는 Python 3.11 이상과 표준 라이브러리만 필요하다. 새 의존성 설치 없이 `python scripts/check_workspace.py`를 실행한다. Windows에서 python 대신 py를 사용하는 경우 `py -3 scripts/check_workspace.py`를 쓴다.

## 작업·Git 기준
`docs/cb-001-short-topic`, `feat/cb-002-short-topic`처럼 종류/작업ID-설명 형식을 권장한다. commit은 `docs: CB-001 협업 규칙 보강`처럼 목적 하나로 묶는다. `main`은 통합 기준선으로 사용하며 첫 저장소 기준선 업로드 후 작업 branch→PR(변경 검토 요청)→검토→통합 순서를 권장한다. 실제 병합 권한·필수 리뷰 수·보호 branch 설정은 아직 미정이다.

변경 전에 `git status`, 반영 전에 `git diff --check`와 `git diff --stat`를 확인한다. `git add <확인한 파일>`로 지정한 변경만 stage한다. 테스트 로그·비밀·다른 담당 변경을 한꺼번에 넣지 않는다. 원격 작업은 그 시점 사용자 요청과 저장소 정책 범위 안에서 한다. push·PR·병합이 서로 다른 행동임을 구분한다. 시간 경과나 검토자 부재를 승인으로 해석하지 않는다.

줄바꿈: Git은 줄바꿈을 변환하지 않고 바이트 그대로 저장한다(`.gitattributes`의 `* -text`). 이 저장소가 파일 SHA256으로 무결성을 검증하기 때문이다. 새로 만들거나 고치는 텍스트 파일은 `.editorconfig`에 따라 LF로 쓴다. `prototype/data`·`prototype/evidence`·`prototype/source-provenance`와 `prototype/examples/terra-execution.json`은 다른 파일에 해시가 기록된 실행·출처 기록이므로 바이트를 바꾸지 않는다.

## 공동 작업
담당은 사람 이름 대신 작업 카드의 owner와 allowed_paths로 배정한다. 실제 계정·CODEOWNERS·가짜 담당자를 미리 만들지 않는다. 공용 문서·계약 파일은 통합 담당이 변경을 모아 반영한다. 다른 경로가 필요하면 작업 범위와 의존성을 갱신하고 충돌이 없는지 확인한다.

충돌 시 양쪽 변경과 요구를 비교한다. 다른 사람의 변경을 통째로 선택해 버리지 않는다. 해결 후 같은 검사를 다시 수행하고 검토·인계에 기록한다. 강제 push·강제 reset·정리 명령으로 사용자 작업을 없애지 않는다. 권한이 없는 변경은 패치와 이유를 인계한다.

## 완료와 검토
[작업 템플릿](docs/templates/TASK.md), [검토 템플릿](docs/templates/REVIEW.md), [인계 템플릿](docs/templates/HANDOFF.md)을 사용한다. 실측 증거가 없는 항목은 미실행으로 남긴다. 문서 CI 통과는 CAD 성공이나 승인·보안 강제의 구현을 뜻하지 않는다.

`.env.example`은 현재 설명만 제공하며 키가 필요 없다. 원본 benchmark와 설계 맥락은 통째로 Git 제외하지 않는다. 권리·비밀 여부·용량을 검토하고 필요하면 별도 보존 위치와 해시를 기록한다. LICENSE는 소유자 결정 전 추가하지 않는다.
