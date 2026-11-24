# depbee Actions 시연

npm 의존성 변경을 GitHub Actions에서 검사하는 흐름을 보여 주는 소비자 저장소입니다. 기준 프로젝트는 `ms@2.1.1` 하나를 쓰는 `package.json`과 `package-lock.json`입니다. 어떤 workflow도 npm 패키지를 설치하거나 실행하지 않습니다.

## 제품 검사와 fixture 시연

이 저장소에는 서로 섞이지 않는 두 경로가 있습니다. 제품 검사는 공개 저장소 [depbee](https://github.com/26-Capstone-Project-Team01/depbee)의 Action을 PR에서 실제로 실행합니다. fixture 시연은 저장소에 넣어 둔 고정 입력(fixture)과 가상 목록으로 세 장면의 화면을 보여 줍니다. 제품 검사는 lockfile 항목의 이름과 버전을 depbee에 든 기지 악성 색인과 대조해 일치하면 실패합니다. 시연용 가상 이름 `DEPBEE-DEMO-SENTINEL`은 그 색인에 없으므로 제품 검사에서는 일치가 나오지 않습니다. 그래서 실패 화면은 fixture 시연이 가상 목록으로 재현합니다.

| 구분 | fixture 시연 | 제품 검사 |
|---|---|---|
| workflow 파일 | `fixture-demo.yml`, `fixture-pr-check.yml` | `depbee.yml` |
| 실행 시점 | 수동 실행, `main` 대상 PR | `main` 대상 PR |
| 실행하는 코드 | 이 저장소의 `tools/fixture_gate.py` | 40자 커밋 SHA로 고정한 depbee Action. Release, 저장소 변수, secret 없이 호출합니다. |
| 판정 근거 | lockfile의 이름과 버전, 가상 목록 `fixtures/known-list.json` | 고정한 커밋의 depbee에 들어 있는 기지 악성 색인과 모델의 ML 위험 점수 |
| 결과의 의미 | 화면과 흐름의 시연입니다. 보안 판정이 아닙니다. | depbee의 실제 판정입니다. |
| PR에 나오는 job | `PR lockfile fixture 판정 (보안 게이트 아님)` | `depbee scan (제품 실제 검사)` |
| job summary의 제목 | `fixture 시연 결과` | `depbee 검사 결과` |
| artifact | 이름이 `fixture-report`로 시작합니다. `fixture-report.json`의 `depbee_executed`가 `false`입니다. | 이름이 `depbee-report`입니다. `report.json`에 `model_id`가 있습니다. |

`main` 대상 PR에는 두 검사가 함께 나옵니다. fixture 시연의 성공은 depbee가 검사해서 통과했다는 뜻이 아닙니다. fixture 시연의 workflow 이름에는 `depbee 제품 미실행`이, 게이트를 실행하는 job 이름에는 `보안 게이트 아님`이 붙어 있습니다. 실행할 때마다 같은 내용의 notice 주석과 job summary 첫 문단이 나옵니다.

## 제품 검사

`main` 대상 PR마다 `depbee.yml`의 `depbee scan (제품 실제 검사)` job이 depbee Action을 실행합니다. Action은 PR의 기준 커밋과 PR의 `package-lock.json`을 비교해 바뀐 항목을 찾고, 그 버전의 tarball을 npm registry에서 받아 읽기만 합니다. lockfile을 바꾸지 않은 PR에서는 바뀐 의존성 0개로 통과하며, 이전 고정 커밋 `759cc68`로 실행한 [이 실행](https://github.com/26-Capstone-Project-Team01/depbee-actions-demo/actions/runs/45290763429)이 그 예입니다.

job의 단계는 아래 둘뿐입니다. Release, 저장소 변수, secret은 필요 없고 workflow 권한은 `contents: read`입니다. 다른 저장소에서 쓸 때도 `pull_request` 이벤트로 실행하는 job에 이 두 단계를 넣습니다.

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  with:
    fetch-depth: 0
    persist-credentials: false
- uses: 26-Capstone-Project-Team01/depbee@0a68fed3701743d6e68b0c61a3ca208e7dc3f646
  with:
    max-changes: '1'
```

- 모델과 기지 악성 색인은 고정한 커밋의 depbee 설치본에 들어 있고, 같은 커밋의 depbee CLI가 기본으로 쓰는 것과 같습니다. 이 커밋의 모델 ID는 `D04-E00`이고 기지 악성 색인의 기준 시점은 `2026-10-06T14:00:47Z`입니다. 이 저장소에는 모델과 색인을 두지 않습니다.
- 실행에 쓰인 값은 그 실행의 결과에 나옵니다. job summary에는 `모델 ID`와 `기지 악성 색인 기준 시점`으로, artifact `depbee-report`의 `report.json`에는 `model_id`와 `detectors.known_malicious.list_as_of`로 적힙니다.
- 색인은 기준 시점까지의 기록만 담습니다. 그 뒤에 알려진 악성 버전은 일치로 나오지 않습니다.
- `fetch-depth: 0`은 PR의 기준 커밋에 있는 lockfile과 비교하기 위한 설정입니다.
- Action은 기준 커밋을 `pull_request` 이벤트에서 받습니다. 다른 이벤트에는 기준 커밋이 없어 Action이 입력 오류로 실패하므로 이 workflow에는 수동 실행이 없습니다. 수동 시연은 `fixture-demo.yml`로 합니다.
- 저장소 변수와 secret을 쓰지 않으므로 fork나 Dependabot이 연 PR에서도 Action이 받는 입력은 같습니다.

판정 규칙은 고정한 커밋의 depbee [GitHub Action 문서](https://github.com/26-Capstone-Project-Team01/depbee/blob/0a68fed3701743d6e68b0c61a3ca208e7dc3f646/docs/ci-cd.md)를 따릅니다. 기지 악성 일치는 실패입니다. ML 위험 점수 기준 이상과 보류는 경고입니다. 입력 오류, depbee 설치 실패, 설치본에 든 모델·색인의 해시 불일치, 모델 ID나 색인 기준 시점이 없는 보고서는 실패입니다. 장면마다 lockfile 항목 하나만 바뀌므로 `max-changes`를 1로 두었습니다. 항목을 둘 이상 바꾼 PR은 검사 없이 실패합니다.

### 정상 변경 PR로 확인하기

`pass` 장면은 `ms`를 2.1.1에서 2.1.3으로 올리는 정상 변경입니다. 이 변경을 PR로 올리면 제품 검사가 `ms@2.1.3`을 실제로 분석합니다.

최신 원격 `main`에서 고유한 이름의 장면 브랜치를 만들고, 장면 lockfile을 루트로 복사해 `main`으로 PR을 엽니다. 아래 명령은 브랜치 이름에 UTC 초 단위 시각을 붙여 열려 있는 장면 PR이 이미 쓰는 `scene/pass` 같은 이름과 구분하고, 같은 이름의 브랜치가 이미 있거나 다른 단계가 실패하면 그 뒤 명령을 실행하지 않고 멈춥니다.

```sh
(
  set -e
  scene=pass
  scene_branch="scene/$scene-$(date -u +%Y%m%dT%H%M%SZ)"
  git fetch origin main
  git switch -c "$scene_branch" FETCH_HEAD
  cp "fixtures/scenarios/$scene/package-lock.json" package-lock.json
  git commit -m "$scene 장면을 재현한다" -- package-lock.json
  git push -u origin "$scene_branch"
  gh pr create --base main --title "$scene 장면" --body "시연용 PR입니다. 병합하지 않습니다."
)
```

PR의 Checks에서 `depbee scan (제품 실제 검사)` job을 열어 아래를 확인합니다.

1. job이 성공이고 주석이 없습니다.
2. job summary의 `depbee 검사 결과` 표에 `ms` 한 행이 있습니다. 판정은 통과, 설치될 버전은 `2.1.3`, 기지 악성은 미적중, ML 위험 점수는 기준 미만입니다.
3. 같은 행의 비교 버전은 `2.1.2`입니다. depbee는 lockfile의 이전 버전 `2.1.1`이 아니라 같은 release line의 직전 stable 버전과 비교합니다.
4. summary의 `depbee Actions 판정` 절에 모델 ID `D04-E00`과 기지 악성 색인 기준 시점 `2026-10-06T14:00:47Z`가 있습니다.

[PR #8](https://github.com/26-Capstone-Project-Team01/depbee-actions-demo/pull/8)은 같은 `ms` 변경을 담은 시연 전용 PR입니다. 그 [제품 검사 실행](https://github.com/26-Capstone-Project-Team01/depbee-actions-demo/actions/runs/45290776914)은 PR #8의 workflow가 고정한 이전 커밋 `759cc68`의 Action으로 주석 없이 성공했고, artifact `depbee-report`의 값이 위 확인 항목과 같습니다. 지금 고정한 `0a68fed`는 `759cc68`과 `action.yml`, 설치본의 모델과 색인, 분석기 고정 커밋이 같습니다. artifact는 보존 기간이 지나면 지워집니다.

`scene`을 `hold-warning`이나 `known-match`로 바꾸면 그 장면의 PR이 열립니다. 같은 PR에서 두 검사는 아래처럼 끝납니다.

| `scene` | 제품 검사 | fixture PR 검사 |
|---|---|---|
| `pass` | 성공, 주석 없음 | 성공, 주석 없음 |
| `hold-warning` | 성공, 경고 1개. 사전 배포 버전은 보류(`out_of_training_scope`)입니다. | 성공, 경고 1개 |
| `known-match` | 성공, 경고 1개. npm registry 주소가 없는 항목은 보류(`unsupported_registry_source`)입니다. | 실패, 오류 1개 |

보류는 검사를 끝내지 못한 항목이며 통과가 아닙니다. `known-match` 장면의 실패는 fixture PR 검사에만 나옵니다. 제품 검사는 npm registry 주소가 있는 항목만 기지 악성 색인과 대조합니다. 주소가 없는 `DEPBEE-DEMO-SENTINEL` 항목은 분석하지 않고 보류로 둡니다.

장면 PR은 병합하지 않고 닫습니다. 병합하면 `main`의 기준 lockfile이 바뀌어 세 장면의 결과가 달라집니다.

### 실제 보고서 내려받기

제품 검사의 전체 결과는 artifact `depbee-report`에 든 `report.json`입니다. 실행 페이지의 **Artifacts**에서 받거나 GitHub CLI로 받습니다. 내려받으려면 GitHub에 로그인해야 합니다. 아래 명령은 검사가 끝난 뒤 장면 브랜치에서 실행합니다.

```sh
run_id=$(gh run list --workflow depbee.yml --branch "$(git branch --show-current)" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run download "$run_id" --name depbee-report --dir depbee-report
```

`depbee-report/report.json`에서 아래 값을 확인합니다.

- `model_id`, `detectors.known_malicious.list_as_of`: 실행에 쓰인 모델과 색인
- `results[].package`, `results[].after_version`, `results[].compared_version`: 분석한 패키지와 비교 버전
- `results[].status`, `results[].known_malicious.status`, `results[].ml.status`, `results[].score`: 판정과 ML 위험 점수
- `provenance.feature_extractor.commit`: 분석에 쓰인 depbee-analyzer 커밋

### 선택 입력: Release의 모델과 색인

고정한 커밋에 든 것과 다른 모델이나 색인을 쓸 때만 Action에 `model-version`, `model-sha256`, `manifest-sha256`, `known-malicious-version`, `known-malicious-sha256` 다섯 입력을 줍니다. 다섯 개를 모두 주면 Action이 depbee Release에서 모델과 색인 파일을 받아 입력의 SHA-256과 비교한 뒤 그 파일만 씁니다. 일부만 주거나 형식이 틀리면 설치와 다운로드 전에 실패합니다. 이 저장소의 workflow는 이 입력을 쓰지 않습니다.

## fixture 시연의 세 장면

| 장면 | 기준 lockfile에서 바뀌는 것 | job 결과 | 주석 |
|---|---|---|---|
| `pass` | `ms`를 2.1.1에서 2.1.3으로 올립니다. | 성공 | 없음 |
| `known-match` | 가상 패키지 `DEPBEE-DEMO-SENTINEL@9.9.9`를 추가합니다. | 실패 | 오류 1개 |
| `hold-warning` | `ms`를 사전 배포 버전 3.0.0-canary.1로 바꿉니다. | 성공 | 경고 1개 |

장면의 대상 lockfile은 `fixtures/scenarios/<장면>/package-lock.json`입니다. 결과는 미리 적어 둔 값이 아닙니다. fixture 게이트가 실행될 때마다 기준 lockfile과 대상 lockfile을 비교해 계산합니다.

`DEPBEE-DEMO-SENTINEL`은 이 시연을 위해 지은 가상의 이름이며 실제 악성 패키지 기록이 아닙니다. npm은 새 패키지 이름에 대문자를 허용하지 않으므로 이 이름으로는 패키지를 새로 올릴 수 없습니다. 장면 lockfile의 이 항목에는 내려받을 주소도 없습니다.

### 장면 실행하기

Actions 탭에서 **fixture 시연 (depbee 제품 미실행)**을 고르고 **Run workflow**에서 `scenario`를 선택합니다. GitHub CLI로는 아래처럼 실행합니다.

```sh
gh workflow run fixture-demo.yml -f scenario=all
```

`scenario`는 `all`, `pass`, `known-match`, `hold-warning` 중 하나입니다. `all`은 자체 테스트 job 하나와 장면 job 세 개를 실행합니다. `known-match` 장면의 기대 결과가 실패이므로 `all`과 `known-match` 실행은 전체가 실패로 끝납니다. 이것이 정상입니다.

### 실행 결과에서 확인할 것

1. job 목록에서 `자체 테스트 (세 장면 기대 결과 검증)`이 성공인지 확인합니다. 이 job은 `tests/`를 실행해 세 장면의 결과와 workflow 규칙이 이 문서와 같은지 검사합니다. 실패하면 장면 job은 실행되지 않습니다.
2. 장면 job의 성공과 실패가 위 표와 같은지 확인합니다.
3. 실행 요약의 Annotations에서 `known-match`의 오류와 `hold-warning`의 경고를 확인합니다. 주석은 대상 lockfile에서 그 패키지의 `packages` 키가 있는 줄을 가리킵니다. 실패한 job에는 GitHub가 붙이는 `Process completed with exit code 1.` 오류도 함께 나옵니다.
4. 각 장면 job의 summary에서 패키지, 이전 버전, 새 버전, fixture 판정, 근거를 확인합니다.
5. artifact `fixture-report-<장면>`의 `fixture-report.json`에서 `verdict`, `results[].status`, `depbee_executed: false`를 확인합니다.

`known-match` job이 실패했다는 사실만으로는 기대한 실패가 아닙니다. 아래 세 가지가 모두 맞아야 기대한 실패입니다.

- 게이트 단계가 종료 코드 1로 끝났습니다. 그 단계의 오류가 `Process completed with exit code 1.`입니다.
- 제목이 `fixture 게이트 (depbee 제품 아님)`인 오류 주석이 `node_modules/DEPBEE-DEMO-SENTINEL` 줄을 가리키고, 내용에 `시연용 가상 목록과 일치(DEMO-FIXTURE-0001)`이 있습니다.
- artifact `fixture-report-known-match`의 `fixture-report.json`에서 `verdict`가 `fail`이고 `results[0].status`가 `known_match`입니다.

종료 코드가 2이거나, 제목이 `fixture 게이트 오류 (판정 아님)`인 주석이 있거나, 보고서가 올라오지 않았으면 게이트가 판정을 끝내지 못한 것입니다. 그 실패는 가상 목록 일치가 아닙니다.

### PR로 재현하기

PR에서는 `fixture PR 검사 (depbee 제품 미실행)`이 제품 검사와 함께 실행됩니다. [정상 변경 PR로 확인하기](#정상-변경-pr로-확인하기)의 명령에서 `scene`을 `pass`, `known-match`, `hold-warning` 중 하나로 정해 장면 PR을 엽니다.

fixture PR 검사의 결과는 수동 실행과 같고, 주석은 `package-lock.json`의 해당 줄을 가리킵니다. fixture 게이트와 depbee Action은 lockfile만 읽으므로 `package.json`은 바꾸지 않아도 됩니다.

### fixture 게이트의 규칙과 한계

fixture 게이트는 대상 lockfile의 `packages` 항목 중 기준에 없거나 이름 또는 버전이 달라진 항목을 차례로 판정합니다.

1. 이름과 버전이 가상 목록에 있으면 `known_match`입니다. 오류 주석을 남기고 종료 코드 1로 job을 실패시킵니다.
2. 이름이나 버전을 해석하지 못하거나 사전 배포 버전이면 `hold`입니다. 경고 주석을 남기고 job은 성공합니다. 보류는 통과가 아닙니다.
3. 그 밖의 항목은 `no_match`입니다.

판정을 끝내지 못하면 종료 코드 2로 실패합니다. 통과로도 가상 목록 일치로도 처리하지 않습니다. 이때 오류 주석의 제목은 `fixture 게이트 오류 (판정 아님)`이고 보고서는 올라가지 않습니다. 원인은 네 가지입니다.

- 입력을 읽지 못했습니다. lockfile이 없거나, 심볼릭 링크이거나, 8 MiB를 넘거나, JSON 객체가 아니거나, `packages`가 없거나(lockfileVersion 1), 변경 항목이 20개를 넘는 경우입니다. 가상 목록을 읽지 못한 경우도 같습니다.
- 결과를 기록하지 못했습니다. 보고서나 summary 파일을 쓸 수 없는 경우입니다.
- 판정을 알리지 못했습니다. 판정 주석을 출력할 수 없거나 완료 신호를 쓸 수 없는 경우입니다.
- 게이트 내부에서 예상하지 못한 오류가 났습니다.

게이트는 보고서와 summary를 쓰고, 판정 주석을 출력한 다음, 마지막으로 step 출력 `report_ready=true`를 완료 신호로 씁니다. workflow는 이 신호가 있을 때만 보고서를 올립니다. 보고서와 summary를 쓰고 판정 주석까지 출력한 뒤 마지막 완료 신호 쓰기에 실패하면 종료 코드 2로 끝나고 보고서도 올라가지 않지만, 이미 출력된 판정 주석은 남을 수 있습니다. 그래서 가상 목록 일치는 종료 코드 1, 일치 주석, 올라온 보고서 세 가지를 함께 확인해야 합니다. 판정을 끝내지 못한 실행에서는 게이트가 보고서 파일을 지우며, 지우지 못한 파일이 남아도 신호가 없어 올라가지 않습니다.

fixture 게이트는 `resolved`나 `integrity`만 바뀐 항목, 삭제된 항목, 패키지 내용, 설치 스크립트, `package.json`을 보지 않습니다. 실제 저장소를 지키는 용도로 쓰지 않습니다.

## 실패의 의미

| 위치 | 실패가 뜻하는 것 |
|---|---|
| fixture 시연의 `known-match` 장면 | 종료 코드 1, 일치 주석, `verdict`가 `fail`인 보고서가 모두 있으면 기대한 결과입니다. 하나라도 없으면 게이트가 판정을 끝내지 못한 실패입니다. |
| fixture 시연의 `pass`, `hold-warning` 장면 | 기대와 다릅니다. 게이트, 가상 목록, 장면 lockfile, 기준 lockfile 중 하나가 바뀌었습니다. |
| fixture 시연의 자체 테스트 | 게이트나 workflow가 이 문서와 다르게 동작합니다. 시연 전에 고쳐야 합니다. |
| fixture PR 검사 | 종료 코드 1, 일치 주석, `verdict`가 `fail`인 보고서가 있으면 PR의 lockfile에 가상 목록과 일치하는 항목이 있습니다. 종료 코드 2이면 게이트가 판정을 끝내지 못했습니다. |
| depbee scan (제품 실제 검사) | depbee가 기지 악성 일치를 찾았거나 검사를 끝내지 못했습니다. lockfile 항목을 둘 이상 바꾼 PR, depbee 설치 실패, 보고서가 없는 실행은 검사를 끝내지 못한 실패입니다. 세 장면의 PR에서는 기대한 결과가 아닙니다. |

실패한 검사가 병합을 실제로 막는지는 저장소의 필수 검사 설정이 정합니다.

## 신뢰 경계

- 모든 workflow의 권한은 `contents: read`입니다. secret과 저장소 변수를 쓰지 않고 checkout 뒤 토큰을 남기지 않습니다(`persist-credentials: false`).
- 모든 Action은 40자 커밋 SHA로 고정했습니다.
- PR 검사는 `pull_request` 이벤트에서만 실행합니다. `pull_request_target`과 `workflow_run`은 쓰지 않습니다.
- 제품 검사 job의 단계는 checkout과 depbee Action 둘뿐입니다. 이 저장소의 workflow에는 PR의 코드나 npm을 실행하는 단계가 없고, 모델과 색인을 고르는 입력도 주지 않습니다.
- depbee Action은 바뀐 버전의 tarball을 npm registry에서 받아 읽기만 합니다. 대상 프로젝트를 설치하거나 빌드하지 않고 npm을 실행하지 않습니다. 분석 캐시를 GitHub Actions 캐시에 저장하지만 캐시는 성능용이며 판정의 근거가 아닙니다.
- fixture PR 검사가 실행하는 코드는 기준 브랜치에서 받은 `tools/fixture_gate.py`뿐이고 `python3 -I`로 실행합니다. PR에서는 `package-lock.json` 한 파일만 받아 데이터로 읽습니다. 게이트나 가상 목록을 고친 PR도 병합 전에는 기준 브랜치의 코드와 목록으로 평가됩니다.
- `pull_request` 이벤트는 PR에 든 workflow 파일을 실행합니다. workflow를 고친 PR은 검사 자체를 바꿀 수 있으므로 `.github/workflows/` 변경은 CODEOWNERS와 브랜치 보호로 리뷰를 거치게 합니다.
- fixture 게이트는 lockfile에서 온 문자열을 신뢰하지 않습니다. 주석, summary, 보고서에 쓰기 전에 인쇄 가능한 ASCII가 아닌 문자를 `\uXXXX`로 바꾸고 120자로 자른 뒤 workflow 명령과 Markdown 규칙으로 이스케이프합니다.
- fixture artifact는 fixture 게이트가 runner 임시 폴더에 쓴 JSON 파일 하나이며 7일 뒤 지워집니다. 게이트가 완료 신호 `report_ready`를 낸 실행에서만 올립니다. 제품 검사의 artifact `depbee-report`는 depbee Action이 올린 `report.json` 하나입니다. 이 저장소의 workflow는 artifact를 내려받아 쓰지 않습니다.
- 장면 lockfile은 시연 입력입니다. 이 파일들로 `npm install`이나 `npm ci`를 실행하지 않습니다.

위 규칙 가운데 텍스트로 확인할 수 있는 것은 `tests/test_workflows.py`가 검사합니다.

## 로컬에서 확인하기

Python 3.12 이상이 필요하고 표준 라이브러리만 씁니다. 저장소 루트에서 실행합니다.

```sh
python tools/fixture_gate.py --head fixtures/scenarios/known-match/package-lock.json
python -m unittest discover -s tests -v
```

첫 명령은 주석 줄과 summary를 터미널에 출력하고 종료 코드 1로 끝납니다. 게이트, 가상 목록, 장면 lockfile, workflow를 바꾼 뒤에는 테스트를 실행하고, 올린 브랜치에서 `gh workflow run fixture-demo.yml --ref <브랜치> -f scenario=all`로 runner에서도 확인합니다.

## 구성

| 경로 | 내용 |
|---|---|
| `package.json`, `package-lock.json` | 기준 프로젝트(`ms@2.1.1`) |
| `fixtures/known-list.json` | fixture 시연 전용 가상 목록 |
| `fixtures/scenarios/` | 장면별 대상 lockfile |
| `tools/fixture_gate.py` | fixture 게이트 |
| `tests/` | 게이트 동작과 workflow 규칙 테스트 |
| `.github/workflows/fixture-demo.yml` | 수동 실행으로 세 장면 재현 |
| `.github/workflows/fixture-pr-check.yml` | PR의 lockfile 변경을 fixture 게이트로 평가 |
| `.github/workflows/depbee.yml` | `main` 대상 PR의 제품 검사 |
