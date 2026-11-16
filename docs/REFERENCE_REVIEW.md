# 참고 저장소 검토와 적용
2026-11-16 KST에 사용자 지정 [void_hackathon](https://github.com/yenaaaaaaaaaaaaaaa/void_hackathon)을 연결된 GitHub에서 읽었다. 확인 commit: `d3c8935ebdf1ea980a4dfad942d9b8b2ed78c7fa`. 이 저장소는 순수 참고용이며 CADBridge 업로드 대상이 아니다.

직접 확인한 범위: 루트 파일·재귀 트리, README, AGENTS, CONTRIBUTING, .gitignore, .env.example, docs/requirements, .github/workflows/pages.yml. 프로그램 코드·데이터 전체를 검토하거나 실행한 것은 아니다.

| 관측한 방식 | CADBridge 적용 |
|---|---|
| 루트 AGENTS와 CONTRIBUTING 분리 | 에이전트 공통 규칙과 사람용 시작 절차 |
| 담당 폴더·계약 변경 기록 | 작업별 allowed_paths와 모듈 경계 계약 목록 |
| branch→PR→검토·작은 commit | 새 기준선 이후 작업별 branch·검토·인계 |
| 환경변수 예제와 비밀 제외 | 키 없는 설명용 .env.example |
| README의 실행·시험 안내 | 의존성 설치 없는 문서 검사 명령 |
| GitHub Actions 배포 파일 | CADBridge는 배포 없이 문서 검사 CI만 새로 작성 |

해커톤 시간제한·시간 경과 후 자기 merge·서비스 문구·웹앱 기술 스택·raw 데이터 일괄 제외·자동 배포는 적용하지 않는다. 문서에서 언급한 data-contract 파일은 확인한 트리에서 찾지 못했으므로 존재를 전제하지 않는다. 우리 계약 목록은 별도로 작성했다.

참고 저장소의 서비스 코드·데이터·문서 원문은 이 패키지에 복사하지 않았다. 이번 검토는 저장소 전체의 품질·보안·테스트 통과 보증이 아니다. 참고 저장소는 수정하지 않는다.
