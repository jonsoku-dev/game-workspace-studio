# 격리된 로컬 설치

이 설치기는 명시한 게임 workspace에서 기존 세 패키징 명령을 실행하고, 새 목적지에 `game-studio`, `pixel-asset-pipeline`, `model-assets`를 설치한다. 사용자 기본 Codex 홈과 기존 등록은 수정하지 않는다. 목적지의 `codex-home`, `venv/bin/pixel-asset`, 세 플러그인, 잠금 파일의 Three.js 및 Phaser를 함께 사용한다. 공급자 서비스나 API 키는 필요 없다.

## 호스트 사전 준비

macOS/Linux, Python 3.10+ (`venv`, `ensurepip` 포함), Codex CLI (`plugin marketplace add`, `plugin add`, `plugin list --json` 지원), Node.js/npm, Blender, Webstage CLI가 PATH에 있어야 한다. 이 실행 파일과 Webstage의 컴파일 도구는 설치기가 설치하지 않는다. 사용하는 Webstage 배포판의 로컬 컴파일 도구도 연결 가능한 준비 환경에서 미리 설치해야 한다. Node.js 22+와 Blender 5.2 LTS를 기준으로 준비한다. Blender의 `--offline-mode` 지원이 필요하다.

소스 workspace에는 `studio/`와 `assets/`가 모두 있어야 한다. 각 저장소의 배포 리비전을 고정해서 받는다. 소스 코드, CLI, Blender, Webstage 도구의 설치와 아래 의존성 취득은 **런타임/오프라인 설치 전에** 끝낸다. 이 문서의 bootstrap 범위는 Python venv/픽셀 CLI, 로컬 플러그인 등록, Three.js다. Blender 렌더와 Webstage 컴파일 성공은 별도 제작 검증이다.

## 연결 가능한 준비 환경에서 의존성 취득

경로는 운영자가 명시한다. 공백을 포함해도 된다. wheel은 대상 OS·CPU·Python 버전과 맞아야 한다. 아래 `python3`와 실제 설치 명령의 Python을 일치시킨다. 다른 장비로 옮길 때는 준비 폴더를 전달하며 개발자 개인 캐시는 필요 없다.

```sh
WORKSPACE="/absolute/path/to/game-workspace"
INPUTS="/absolute/path/to/prepared-inputs"
mkdir -p "$INPUTS/wheels" "$INPUTS/npm-cache"
PYTHON=/absolute/path/to/python3.13
"$PYTHON" -m pip download --only-binary=:all: --dest "$INPUTS/wheels" \
  'Pillow==12.0.0' 'setuptools==80.9.0' 'wheel==0.45.1'
PREPARE=$(mktemp -d)
cp "$WORKSPACE/assets/plugins/model-assets/three/package.json" "$PREPARE/"
cp "$WORKSPACE/assets/plugins/model-assets/three/package-lock.json" "$PREPARE/"
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

설치기는 빈 임시 환경에서 wheel/npm 입력을 사전 검사한 뒤 목적지를 만들고, 실제 Codex 등록 결과, 설치된 픽셀 CLI의 `--help`, Three.js 버전과 모듈 import를 검사한다. 성공하면 stdout JSON의 `status`가 `ready`이고 `install-result.json`, `env.sh`가 생긴다. 이는 제작물의 시각 품질·게임 통합 검증이 아니다.

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

0.5.x는 `studio/engines/web/phaser/package.json 및 package-lock.json`의 Phaser 3.90.0과 eventemitter3도 같은 npm 캐시에 준비해야 한다. 임시 폴더에 이 두 파일을 복사하고 Three와 동일한 `npm ci --cache "$INPUTS/npm-cache" --ignore-scripts --no-audit --no-fund`를 실행한다. 런타임은 패키지 무결성과 배포 파일·라이선스의 고정 SHA-256을 검사한다.
