# depbee Actions 시연

npm 의존성 변경 PR을 열면 depbee가 변경된 lockfile 항목을 검사합니다. 기본 브랜치에는 `ms@2.1.1` 하나가 있습니다. 아래 세 브랜치는 각각 `main`에서 독립적으로 갈라지며 패키지 이름·버전·배포 메타데이터만 변경합니다. 패키지 설치 없이 시연할 수 있습니다.

| PR 브랜치 | 변경 | 기대 결과 |
|---|---|---|
| `demo/pass` | ms를 2.1.3으로 업데이트 | D04-E00 기준 정상 분석 완료, Check 성공 |
| `demo/known-fail` | 기지 악성으로 기록된 버전을 하나 추가 | 색인의 이름·버전 일치, Check 실패와 오류 주석 |
| `demo/hold-warning` | ms를 3.0.0-canary.1로 변경 | 사전 배포 버전으로 분석 보류, Check 성공과 경고 주석 |

기지 악성 장면은 lockfile의 `integrity`를 의도적으로 생략합니다. depbee는 이 항목의 tarball 추출을 건너뛰고 이름·버전만 색인과 대조합니다. 이 PR은 검사 화면에서만 사용합니다. 정상·보류 장면에는 버전에 해당하는 integrity가 있습니다.

## 실제 PR을 열기 전에

1. depbee와 분석기 저장소 `26-Capstone-Project-Team01/depbee-analyzer`가 익명으로 접근 가능해야 합니다. 워크플로의 depbee 고정 SHA는 준비 시점의 `3d2b186`입니다. 공개 시연 전 분석기 설치 URL과 Action의 고정 커밋 추출 코드가 새 저장소 이름을 지원하는지 확인하고, 검증된 depbee 커밋의 40자 SHA를 `uses`에 고정합니다. `main`을 갱신하면 세 PR 브랜치도 같은 워크플로 커밋을 기준으로 맞춥니다.
2. 공개된 depbee Release의 모델·색인 파일을 익명으로 받아 SHA-256을 대조하고 아래 값을 데모 저장소의 **Settings > Secrets and variables > Actions > Variables**에 등록합니다. 모델 파일은 `model.txt`, `manifest.json`입니다. 색인 파일은 `known-malicious-index.json`, `known-malicious-manifest.json`입니다. 색인에 기지 악성 장면의 이름·버전이 들어 있는지도 확인합니다.

| 저장소 변수 | 값 |
|---|---|
| `DEPBEE_MODEL_VERSION` | 모델 Release 태그 |
| `DEPBEE_MODEL_SHA256` | model.txt의 소문자 64자리 SHA-256 |
| `DEPBEE_MANIFEST_SHA256` | 모델 manifest.json의 소문자 64자리 SHA-256 |
| `DEPBEE_KNOWN_MALICIOUS_VERSION` | 색인 Release 태그 |
| `DEPBEE_KNOWN_MALICIOUS_SHA256` | known-malicious-index.json의 소문자 64자리 SHA-256 |

준비 시점에는 공개 Release가 없습니다. 필수 변수가 비거나 파일 다운로드·해시 검증에 실패하면 Check도 실패합니다. 이 경우 탐지 결과가 나오기 전이므로 기지 악성 장면의 성공 조건에 포함하지 않습니다.

## 시연

공개 범위를 확인한 뒤 각 브랜치를 별도 PR로 열고 기준 브랜치는 모두 `main`으로 둡니다. 기지 악성 이름과 버전도 공개 PR 이력에 남으므로 해당 장면은 공개 동의 후에 올립니다. Job summary와 `depbee-report` artifact에서 변경 한 건의 판정을 확인합니다. 기지 악성 장면은 `known_malicious.status=hit`, 보류 장면은 `status=incomplete`와 경고, 정상 장면은 `status=not_flagged`까지 확인합니다. 보류도 기본 Check는 초록색입니다. 시연 후 PR을 닫아 기준 프로젝트를 유지합니다.

로컬에서는 `git diff main...demo/pass -- package.json package-lock.json`으로 변경을 확인할 수 있습니다. 끝의 브랜치 이름을 바꾸면 다른 장면도 같은 방식으로 볼 수 있습니다. CI는 신뢰한 Action만 호출합니다. 소비자 프로젝트의 npm, 설치 스크립트, PR에 들어 있는 코드는 실행할 필요가 없습니다.
