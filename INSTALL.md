# 격리된 로컬 설치

이 설치기는 명시한 게임 workspace에서 기존 세 패키징 명령을 실행하고, 새 목적지에 `game-studio`, `pixel-asset-pipeline`, `model-assets`를 설치한다. 사용자 기본 Codex 홈과 기존 등록은 수정하지 않는다. 목적지의 `codex-home`, `venv/bin/pixel-asset`, 세 플러그인, 잠금 파일의 Three.js 및 Phaser를 함께 사용한다. 공급자 서비스나 API 키는 필요 없다.

## 호스트 사전 준비

macOS/Linux, Python 3.10+ (`venv`, `ensurepip` 포함), Codex CLI (`plugin marketplace add`, `plugin add`, `plugin list --json` 지원), Node.js/npm, Blender, Webstage CLI가 PATH에 있어야 한다. 이 실행 파일과 Webstage의 컴파일 도구는 설치기가 설치하지 않는다. 사용하는 Webstage 배포판의 로컬 컴파일 도구도 연결 가능한 준비 환경에서 미리 설치해야 한다. Node.js 22+와 Blender 5.2 LTS를 기준으로 준비한다. Blender의 `--offline-mode` 지원이 필요하다.

소스 workspace에는 `studio/`와 `assets/`가 모두 있어야 한다. 각 저장소의 배포 리비전을 고정해서 받는다. 소스 코드, CLI, Blender, Webstage 도구의 설치와 아래 의존성 취득은 **런타임/오프라인 설치 전에** 끝낸다. 이 문서의 bootstrap 범위는 Python venv/픽셀 CLI, 로컬 플러그인 등록, 고정된 Three.js와 Phaser다. Blender 렌더와 Webstage 컴파일 성공은 별도 제작 검증이다.

## 연결 가능한 준비 환경에서 의존성 취득

경로는 운영자가 명시한다. 공백을 포함해도 된다. wheel은 대상 OS·CPU·Python 버전과 맞아야 한다. 아래 `python3`와 실제 설치 명령의 Python을 일치시킨다. 다른 장비로 옮길 때는 준비 폴더를 전달하며 개발자 개인 캐시는 필요 없다.

```sh
WORKSPACE="/absolute/path/to/game-workspace"
INPUTS="/absolute/path/to/prepared-inputs"
mkdir -p "$INPUTS/wheels" "$INPUTS/npm-cache"
PYTHON=/absolute/path/to/python3.13
"$PYTHON" -m pip download --only-binary=:all: --dest "$INPUTS/wheels" \
  'Pillow==12.0.0' 'setuptools==80.9.1' 'wheel==0.45.1'
PREPARE=$(mktemp -d)
cp "$WORKSPACE/assets/plugins/model-assets/three/package.json" "$PREPARE/"
cp "$WORKSPACE/assets/plugins/model-assets/three/package-lock.json" "$PREPARE/"
(cd "$PREPARE" && npm ci --cache "$INPUTS/npm-cache" \
  --ignore-scripts --no-audit --no-fund)
cp "$WORKSPACE/studio/engines/web/phaser/package.json" "$PREPARE/"
cp "$WORKSPACE/studio/engines/web/phaser/package-lock.json" "$PREPARE/"
(cd "$PREPARE" && npm ci --cache "$INPUTS/npm-cache" \
  --ignore-scripts --no-audit --no-fund)
```

`PREPARE`는 운영자가 만든 임시 작업 폴더다. 설치에는 `wheels`와 `npm-cache`만 전달한다. Three.js는 소스의 package-lock.json 버전·integrity에 고정되며, 현재 0.187.0이다. Python의 bootstrap 의존성도 위 세 버전에 고정된다. wheel 파일 자체의 별도 서명 검증/해시 잠금은 제공하지 않으므로 신뢰하는 준비 환경과 보관소를 사용한다.

## 오프라인 설치와 실행

설치 목적지는 소스·준비 입력 밖의 새 경로를 고른다. 기존 임의 디렉터리를 재사용하지 않는다. 설치는 항상 pip `--no-index`, npm `--offline --ignore-scripts`를 사용하며 누락된 의존성을 온라인 취득하지 않는다. Codex는 로컬 marketplace 경로만 등록한다. 이는 OS 차원의 네트워크 차단 기능은 아니다.

```sh
DESTINATION="/absolute/path/to/game-environment"
"$PYTHON" "$WORKSPACE/studio/tools/install_workspace.py" \
  --workspace "$WORKSPACE" --destination "$DESTINATION" \
  --wheelhouse "$INPUTS/wheels" --npm-cache "$INPUTS/npm-cache"
. "$DESTINATION/env.sh"
codex plugin list --json
pixel-asset --help
python3 "$STUDIO_ROOT/tools/scene.py" validate \
  --project "$STUDIO_ROOT/examples/forest-camp"
```

`env.sh`는 이 셸의 CODEX_HOME, PATH, STUDIO_ROOT, MODEL_ASSETS_ROOT를 지정한다. 이후 같은 셸에서 Codex와 제작 명령을 실행한다. `venv/bin`이 PATH 선두이므로 스튜디오가 호출하는 `python3`와 `pixel-asset`이 같은 환경을 사용한다. 새 셸에서는 다시 source한다. 목적지 전체는 절대 경로가 포함된 Python venv와 Codex 등록을 소유하므로 옮기지 말고 새 경로에서 재설치한다.

설치기는 빈 임시 환경에서 wheel/npm 입력을 사전 검사한 뒤 목적지를 만들고, 실제 Codex 등록 결과, 설치된 픽셀 CLI의 `--help`, Three.js 버전과 모듈 import, 고정 Phaser 런타임·라이선스 바이트를 검사한다. 성공하면 stdout JSON의 `status`가 `ready`이고 `install-result.json`, `env.sh`가 생긴다. 이는 제작물의 시각 품질·게임 통합 검증이 아니다.

실패하면 오류에 표시된 사전 조건을 복구하고 **동일한 명령**으로 재시도한다. 같은 소스 바이트로 생성된 부분 설치는 재사용한다. 소스가 바뀌었거나 스테이지 파일이 수정되면 새 목적지를 사용한다. 실패한 환경은 자동 삭제하지 않는다. 한 목적지의 동시 설치는 거부한다. npm 캐시는 npm이 관리하는 준비 저장소이며 설치 도중 캐시 메타데이터가 갱신될 수 있다.

실제 사용자 Codex 홈에 합치는 별도 운영 절차가 필요하다면 기존 marketplace 충돌과 버전을 먼저 검토한다. 이 설치기는 그 작업을 수행하지 않는다.

## 개발자 검증

```sh
python3 -m unittest discover -s "$WORKSPACE/studio/tests" -p test_install_workspace.py -v
INSTALL_TEST_WHEELHOUSE="$INPUTS/wheels" INSTALL_TEST_NPM_CACHE="$INPUTS/npm-cache" \
  python3 -m unittest discover -s "$WORKSPACE/studio/tests" -p test_install_workspace.py -v
```

두 번째 명령은 실제 호스트 CLI를 사용해 임시 목적지에 등록하고 재설치·부분 설치 재시도와 무관한 CODEX_HOME 보존을 검사한다. 첫 번째 명령만 실행했으면 실제 설치 검증은 skipped다. 준비 wheel의 Python/플랫폼이 다르면 올바른 준비 환경에서 다시 취득한다.

셸이나 작업 폴더를 바꾸면 `python3`가 다른 버전으로 해석될 수 있다. wheel을 준비한 인터프리터의 절대 경로를 설치에도 사용한다. 예를 들어 `cp313` macOS arm64 Pillow wheel은 CPython 3.15 환경에서 거부된다. 확인 명령은 `"$PYTHON" -c "import sys,sysconfig; print(sys.executable, sys.version, sysconfig.get_platform())"`이다.

이력: 0.5.x에서 Phaser 3.90.0과 eventemitter3의 오프라인 캐시 준비가 추가됐다. 현재 0.13.1에도 적용되며 위 준비 절차에 포함했다. 런타임은 패키지 무결성과 배포 파일·라이선스의 고정 SHA-256을 검사한다.


## 0.9.1 첫 실행과 재개

설치한 `env.sh`를 source한 같은 셸에서 실행한다. `pixel-asset --help`에 `motion`이 없으면 이전 CLI이므로 새 로컬 패키지 설치를 확인한다. 소스 개발 환경의 `PYTHONPATH=assets/src` 실행은 설치본 검증과 구분한다.

```sh
PROJECT="/absolute/path/to/new-game"
python3 "$STUDIO_ROOT/tools/start.py" new "$PROJECT" \
  --idea "森のロボットが標的を狙って訓練する" --title "森の道場" --language ja --hits 5
python3 "$STUDIO_ROOT/tools/start.py" build "$PROJECT"
python3 "$STUDIO_ROOT/tools/start.py" inspect "$PROJECT"
```

한국어는 `--language ko`를 쓴다. 아이디어 원문·제목·목표·조작·완료 기준을 고정하며 기본 규칙은 이동 후 표적에 1..20회 명중하기다. 임의 아이디어의 규칙을 자동 구현하지 않는다. 자체 CC0 master와 명시적 rig, 새 프로젝트용 workspace manifest가 포함되어 외부 이미지나 서비스를 찾을 필요가 없다. 빌드는 로컬 motion → action-set → Studio → Phaser 경로이며 정상 설치된 고정 의존성을 사용한다. `--kind 3d`는 포함된 forest-camp 요청으로 첫 관찰용 장면을 만든다.

`inspect`, `status`, `resume`는 현재 파일과 그래프에서 다음 명령을 출력한다. 새 프로젝트는 `build_required`, 엔진 파일 준비는 `playable_export`, 3D 장면 준비는 `scene_ready`다. 변경·부분 motion은 검사 대상으로 남고 자동 덮어쓰기를 하지 않는다. 출력된 HTTP 서버 명령을 실행한 뒤 주소를 연다. `playable_export`는 서버가 이미 시작됐거나 게임 목표·외형 검수가 끝났다는 뜻이 아니다.

Phaser 브라우저 검사는 실제 설치 파일로 실행한다.

```sh
python3 "$STUDIO_ROOT/tools/playcheck.py" run \
  --project "$PROJECT" --export play/run-실제출력ID
```

`--export`는 `start.py` 출력에서 확인한 **프로젝트 상대** Phaser 납품 디렉터리다. 이 명령에는 Python 3.11+ (`tomllib`)와 `$CODEX_HOME/config.toml` (미지정 시 `~/.codex/config.toml`)의 활성 `mcp_servers.stagehand`, `env.STAGEHAND_BROWSER="local"`, 준비된 로컬 브라우저가 필요하다. 격리 설치의 `env.sh`는 별도 `$CODEX_HOME`을 선택한다. 해당 홈에도 승인된 로컬 Stagehand 설정을 준비해야 하며, 설치기는 기존 홈의 설정이나 자격 증명을 자동 복사하지 않는다. 서버는 검사 중 임시 포트에만 열고 종료한다. 실패/사용 불가는 실제 플레이 통과로 기록하지 않는다. 반환된 `checks/browser-*.json`은 정상 입력·명중·완료·재시작과 실제 전달 바이트의 해시를 담고 그래프에 연결된다. 사용 범위와 사람 판단 게이트는 [GRAPH](GRAPH.md#동작-수정과-ab-검수)를 따른다.

## 배포 파일 스테이징

`python3 "$WORKSPACE/studio/tools/stage.py" --out /새/플러그인/폴더`는 명시된 설치 파일만 새 폴더로 복사한다. 0.13.1은 시작 템플릿, start/revise/review, browser playcheck, 읽기 전용 A/B 화면을 포함한다. 이 명령만으로 Python CLI·npm 의존성·Codex 등록이 설치되지는 않는다. 실제 사용은 위 `install_workspace.py`의 설치·검증 결과와 설치된 명령으로 확인한다. 기존 설치를 갱신할 때는 변경된 소스에 맞는 새 목적지를 선택한다.

## 0.9.1 상태별 작화 → Rive 실행

`pixel-asset --help`에 `character`가 있는 설치본이 필요하다. Studio의 `tools/character.py`는 별도 서비스나 게임 엔진 없이 설치된 `pixel-asset character --request ... --out ...`을 호출한다. 최신 Pixel Asset Pipeline의 Rive 제작·플레이어 의존성을 함께 준비한다. 이 문서의 기존 Python/Phaser 준비만으로 Rive 제작 성공을 보장하지 않는다.

```sh
python3 "$STUDIO_ROOT/tools/character.py" --project "$PROJECT" \
  --request art/character.request.json --out characters/hero-1
```

기본 권장 경로는 상태별 작화 PNG의 `frames` manifest다. `reference`는 외형 기준일 뿐 자동 동작 생성 입력이 아니다. 자동 컷아웃은 명시적으로 원하는 경우에만 사용한다. 요청 형식과 결과는 [README의 PNG → Rive](README.md#png--rive-캐릭터-080)를 따른다. 설치본 지원, 파일 생성, 실제 플레이어 재생, 사람의 외형 승인을 각각 확인한다. staging에는 character.py가 포함되며 실제 설치·사용자 홈 변경은 별도 설치 작업이다.

## 0.9.1 피드백이 있는 첫 게임

`start.py new`의 `--mode courier_trial`은 우편 배달 규칙과 이동·착지·획득·거절·명중 효과를 포함한다. 기본 `land_hits`와 기존 씬은 계속 지원한다. 픽셀 효과 생성에는 Pixel Asset Pipeline 0.8.0을 사용한다. 웹 게임의 소리 합성은 배포 폴더에 있는 모듈과 브라우저 Web Audio로 동작하며 기본값은 음소거다. [제작 명령과 확인 예시](FEEDBACK.md)


## 0.10.0 독립 웹 게임

위 설치로 활성화된 `$STUDIO_ROOT/tools/web_game.py`가 장르별로 작성한 로컬 HTML 게임을 게시한다. 프로젝트에서 `genre.json`과 `game/index.html`을 준비한 뒤 `--project "$PROJECT" --out build/play`를 사용한다. 성공 응답의 `receipt`에 빌드한 진입점과 파일별 해시가 있다. 프로젝트 그래프는 입력 관찰과 출력을 연결한다. 프로젝트마다 새 출력 디렉터리를 사용한다.

## 0.11.0 제작 인터뷰와 웹 캠페인

설치된 스킬은 재미와 아트에서 열려 있는 결정을 사용자와 먼저 정한다. `PLAYBOOK.md`의 이벤트별 연출 설계와 `starter/campaign/`의 두 단계 예시를 함께 설치한다. [새 프로젝트 생성과 게시](README.md#다음-판이-있는-웹-게임)를 따라 실제 승리, 계속, 재도전을 점검한다.

## 0.12.0 수정판 제작과 버그 회귀 검사

설치본의 `tools/web_revision.py`는 같은 프로젝트의 등록된 기준판을 검사하고 변경 요약·새 후보·검증 기록을 만든다. `--kind bugfix`에는 로컬 Stagehand가 필요하다. [명령과 검사 예시](README.md#웹-게임-수정과-버그픽스)

## 0.13.1 자료 반영과 예방 검사

설치 패키지의 `REFERENCES.md`와 `tools/reference_review.py`로 첨부별 제작 판단과 실제 파일을 대조할 수 있다. `web_revision.py check`는 등록된 배포본에서 기본 모바일 검사를 실행한다. `--check`로 해당 게임의 입력·상태·배치 검사를 선택할 수 있다. [자료·예방 검사 사용법](README.md#첨부-자료-반영-점검)
