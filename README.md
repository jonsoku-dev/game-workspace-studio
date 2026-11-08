# Game Studio

게임 기획과 씬 배치, 설치된 에셋 제작기의 엔진 통합을 담당하는 로컬 Codex 플러그인이다. Python 3.10+ stdlib CLI가 실제 제작기를 호출해 프로젝트 상대 경로를 담은 런타임 씬을 만든다. 모델·픽셀 제작 코드는 포함하지 않는다.

## 채팅에서 첫 게임 만들기

예시 요청은 “달빛 아래 로봇이 표적을 세 번 맞히면 끝나는 게임을 만들고, 준비 동작을 조금 늘린 버전도 비교해 줘”다. 새 프로젝트의 `start.py new/build`가 원본 기획과 목표·조작·완료 조건을 기록하고 첫 Phaser 게임을 만든다. `revise.py`는 원본 실행을 고정하고 바꿀 동작만 새 후보로 만든다. `playcheck.py run`은 실제 게임을 열어 거리·방향·접촉·승리·재시작을 검사한다. 작업실의 A/B 탭에서 같은 시각으로 움직이거나 두 게임을 각각 열 수 있다. `?view=compare&lang=ja`로 일본어 비교 화면을 공유한다. 사람의 선택은 채팅에서 검수 기록으로 남긴다. [시작·설치 명령](INSTALL.md) · [수정과 채택 예시](GRAPH.md#동작-수정과-ab-검수)

## 실행

설치된 `pixel-asset` 명령과 활성 `model-assets` 플러그인이 필요하다. Blender·컴파일러 의존성은 3D 제작기가 소유한다.

```sh
python3 tools/scene.py validate --project examples/forest-camp
python3 tools/scene.py build --project examples/forest-camp --out build/run-1
python3 -m unittest discover -s tests -v
```

예시는 보상 효과와 0.3m 등불을 제작해 같은 위치에 배치한다. stdout은 JSON 한 개이고 오류는 stderr JSON 및 종료 코드 2다. `--timeout`은 제작기 호출별 초 단위 제한이며 기본값은 300이다. 새 출력 경로를 사용해야 한다. 실패 산출물은 남겨 두고 `build/run-2`처럼 새 경로로 재시도한다.

3D는 `codex plugin list --marketplace model-assets --json`의 활성 설치 버전으로 `$CODEX_HOME/plugins/cache/model-assets/model-assets/<version>/tools/build.py`를 찾는다. CODEX_HOME 기본값은 `~/.codex`다. 명시적 설치본 테스트에는 `MODEL_ASSETS_ROOT`를 지정한다. 목록의 source 경로는 캐시 위치로 간주하지 않는다. 호출은 `python3 <root>/tools/build.py --request <json> --out <fresh-directory>`다. 2D는 PATH의 `pixel-asset effect`를 사용한다.

## 프로젝트와 런타임 계약

[scene.json](examples/forest-camp/scene.json)은 schema_version 1이다.

- `brief`는 `title`, `goal`, `controls` 문자열을 가진다.
- `assets`는 고유 `id`, `producer` (`pixel-effect`, `pixel-action-set` 또는 `model-assets`), 프로젝트 상대 `request` JSON 경로를 가진다.
- `nodes`는 고유 `id`, `asset` 참조와 `position`, `rotation_degrees`, `scale`의 세 숫자 배열을 가진다. scale은 양수다.
- 좌표는 미터, +Y 위쪽, 오른손 좌표다. 회전은 XYZ Euler 도 단위다. 2D 노드의 양수 `size_m`는 scale 적용 전 정사각형 폭이다. 피벗과 프레임 사각형은 제작 메타데이터를 따른다.
- 요청·출력·번들 파일은 각각의 루트 안에 있어야 한다. 절대 경로와 루트를 벗어나는 심볼릭 링크는 거부한다. 노드의 추가 필드는 보존하며 게임 행동으로 실행하지 않는다.

`build/run-1/scene.runtime.json`은 schema_version, status ready, id, brief, coordinates, assets, nodes를 담는다. `assets[].files`의 **모든 경로는 프로젝트 루트 기준**이다. 런타임 JSON이 있는 폴더 기준이 아니다. 제작기의 반환 키를 보존한다.

| 제작기 | 파일 키 |
| --- | --- |
| pixel-effect | sheet (PNG), metadata (프레임·시간·피벗), preview, effect |
| model-assets | model (컴파일된 GLB), metadata, validation, source, raw, preview, receipt |

3D validation JSON은 `passed: true`여야 한다. 이는 제작기 납품 계약 검사다. 소비 엔진은 모델 메타데이터의 축·단위를 읽고 2D nearest 필터와 프레임별 시간을 적용한다. 실제 플레이나 미적 품질 승인은 별도다.

## 로컬 스테이징

```sh
python3 tools/stage.py --out /tmp/game-studio-stage-1
```

새 로컬 폴더에 manifest, skill, tools, 예시, README를 복사한다. 생성물·이력·원래 2D 데모·Git 저장소는 제외한다. 실제 Codex 홈에 설치하거나 배포하지 않는다. [플러그인 manifest](.codex-plugin/plugin.json)와 [마켓플레이스 manifest](.agents/plugins/marketplace.json)를 포함한다.

기존 2D 보상 효과 납품(소스 저장소의 `assets/generated/reward/sheet.json`)은 보존했다. 게임 조작 구현과 엔진별 임포터는 소비 프로젝트가 소유한다.

## 실행 이력과 입력 보존

그래프가 실행 이력의 유일한 쓰기 원본이다. 그래프 계약과 조회는 [GRAPH.md](GRAPH.md)를 따른다. 각 실행은 UUID, UTC 시작·갱신 시각, PID, 프로젝트 상대 출력, 에셋별 상태를 기록한다. 실행은 running에서 ready 또는 error로 바뀐다. 실패는 원시 stderr 대신 오류 종류와 단계(admission, inputs, discovery, producer, bundle-validation, publish)를 기록한다. 안전한 기존 프로젝트 안에서 입력 검증·기존 출력 충돌 실패도 기록한다. 프로젝트 밖 출력 요청은 쓰기 전에 거부한다.

납품 입력은 출력의 `inputs/scene.json`과 `<asset>.request.json`으로 보존하고 실제 제작기에 그 요청 복사본을 전달한다. 런타임 `input_scene`과 `assets[].request`는 이 복사본의 프로젝트 상대 경로다. 완료된 scene.runtime.json은 원자적으로 게시한다.

출력 디렉터리는 독점 생성하며 동시 실행도 덮어쓰지 않는다. 실패한 출력은 failure.json과 진단 산출물을 보존한다. 자동 재시도·삭제·복구를 하지 않으므로 새 출력 경로로 재시도한다. 강제 종료 후에는 running 기록과 산출물이 남을 수 있다. PID는 진단용이며 PID 재사용 때문에 살아 있는 동일 실행을 보증하지 않는다. CLI ready는 납품 계약 통과를 뜻하며 실제 플레이 검증은 별도다.

기존 모델의 `source_blend`는 원래 요청 JSON의 부모 폴더 기준 상대 경로다. 프로젝트 안에 있는 .blend 파일만 허용한다. 승인 시 해시·크기를 고정하고 출력 inputs로 복사한 실제 바이트와 대조한다. 실행용 요청은 복사한 파일을 기준으로 다시 작성한다. 원래 요청과 실행용 요청은 그래프에서 구분하며 .blend 원문을 그래프에 중복 보관하지 않는다.

`validate`는 파일을 쓰지 않는 구조 검사다. 독립 검토·브라우저·실제 엔진 등 중요한 검증 작업은 프로젝트 안에 증거 파일을 남기고 그래프의 `record` 명령으로 연결한다. 아래는 형식 예시이며 통과한 사실이 있을 때만 passed를 true로 쓴다.

```json
{"id":"engine-review-1","label":"Camp scene engine review","agent":"codex","status":"complete","files":["evidence/engine-review.json"],"verification":{"passed":true,"checks":["lantern placement and reward playback observed"]}}
```

```sh
python3 tools/graph.py record --project examples/forest-camp --record review-record.json
python3 tools/graph.py history --project examples/forest-camp
```

기존 그래프 노드를 직접 관찰한 증거는 record의 observed 배열로 해당 URN에 연결한다. 그래프는 새로운 인과관계를 추측하지 않는다.

## Codex에서 사용

로컬 Codex에 스튜디오를 설치하는 절차다. 아래는 이 버전의 새 설치 경로 예시다.

```sh
python3 tools/stage.py --out "$HOME/.local/share/codex-local-plugins/game-studio/0.8.1"
codex plugin marketplace add "$HOME/.local/share/codex-local-plugins/game-studio/0.8.1"
codex plugin add game-studio@game-studio
STUDIO_ROOT="${CODEX_HOME:-$HOME/.codex}/plugins/cache/game-studio/game-studio/0.8.1"
```

프로젝트에서 `$game-studio`로 기획·씬 제작을 요청한다. 예를 들어 “Forest Camp의 30cm 등불 통풍구에 입체 불티를 붙이고 제작 과정을 보여 줘”라고 지시한다.

```sh
python3 "$STUDIO_ROOT/tools/visualize.py" --project "$PROJECT"
```

출력된 loopback 주소를 Codex에서 열면 이력·에셋·씬·관계를 확인할 수 있다. 씬은 저장된 모델·2D 프레임 시간·피벗·배치를 실제 Three.js에 불러온다. 단발 효과는 검토를 위해 잠시 쉬고 다시 재생한다. 포인터로 실행과 노드를 선택할 수 있다. 새 제작 지시는 채팅에서 한다. 읽기 전용 서버는 그래프에 기록된 해시와 일치하는 로컬 파일만 제공한다.

여러 프로젝트의 관계를 함께 보려면 `--workspace /path/to/workspace.json`을 추가한다. 같은 파일을 `tools/workspace_graph.py /path/to/workspace.json`에 넘기면 등록된 프로젝트를 하나의 JSON-LD 문서로 내보낸다. 실행 세부 기록은 각 프로젝트가 소유한다.

### 3D 씬의 효과

기본 Forest Camp는 3D 등불과 3D 불티를 같은 Model Assets 제작기로 만든다. 불티 노드의 `parent`는 등불 노드 ID이고, 자식 위치·회전·배율은 부모 좌표계 기준이다. Visualizer는 검증된 GLB의 메시 인스턴스를 로컬 궤적에 따라 재생한다. 이전 실행에서 보이는 `pixel-effect`는 카메라를 향하는 2D 스프라이트다. 텍스트 브리프에서 픽셀 연출을 의도한 씬은 계속 이 경로를 사용할 수 있다.

### 2D 캐릭터 씬

`pixel-action-set`은 설치된 `pixel-asset action-set`을 실행한다. 프레임, 효과 시트·메타데이터와 고지 파일의 SHA-256을 그래프에 고정한다. 노드의 `action`으로 원하는 동작을 선택하고 `size_m`로 셀의 표시 폭을 지정한다. 2D 전용 씬에서는 정면 직교 카메라로 캐릭터와 타격 효과의 실제 프레임을 재생한다.

## 운영 설치와 검수

장비 준비 및 독립 설치 절차는 [INSTALL.md](INSTALL.md)에 있다. 설치본은 기존 작업공간의 Codex 설정과 분리할 수 있다.

### 기존 산출물 재사용

씬 자산의 `request` 대신 `"reuse": {"run_id": "<기존 성공 실행 ID>", "asset": "<해당 실행의 에셋 ID>"}`를 둔다. 제작기 종류는 원본과 일치해야 한다. 같은 프로젝트 그래프에 고정된 원본의 크기와 SHA-256을 검사하고 배치된 새 런타임에서 원본 파일을 참조한다. 원본 실행 기록과 파일을 함께 보관한다. 재사용 선택은 미술 승인이 아니다.

### 독립 게임 런타임

[Godot 예제와 내보내기](engines/godot/)는 읽기 전용 visualizer와 분리된다. Studio에서 고정한 에셋을 사용해 실제 입력·공격 접촉·수집·완료·재시작을 실행한다. 엔진 버전과 검증 조건은 어댑터 문서에서 확인한다.

등록한 프로젝트를 한 화면에서 전환하려면 `--workspace /path/to/workspace.json --browse-workspace`를 함께 지정한다. 이 옵션은 해당 manifest에 명시한 모든 프로젝트의 고정된 에셋 열람을 허용한다. 옵션을 생략하면 실행할 때 선택한 프로젝트의 파일만 열린다.

### 게임 엔진에 전달하기

`tools/export_game.py`가 등록된 프로젝트의 성공한 런타임을 읽어 엔진별 폴더와 `engine-export.json`을 새 위치에 게시한다. 사용한 런타임·산출물 ID와 출력 파일 해시를 그래프에 기록한다. 예를 들어 워크스페이스 루트를 출력 소유자로 정하고 다음처럼 실행한다.

```sh
python3 "$STUDIO_ROOT/tools/export_game.py" --engine three --project . --workspace workspace.json \
  --source examples/forest-camp builds/lantern-embers-final/scene.runtime.json --out output/web-3d
python3 "$STUDIO_ROOT/tools/export_game.py" --engine phaser --project . --workspace workspace.json \
  --source examples/scout-actions builds/six-actions/scene.runtime.json --out output/web-2d
```

`godot`과 `unity` 샘플에는 위의 등불·정찰병 두 `--source`를 순서대로 전달한다. Godot 4.5.1은 PCK까지 실행 검증했다. 웹은 Three.js r187과 Phaser 3.90.0으로 로컬 게임을 재생한다. Unity 6000.0.60f1 타깃은 변환·내보내기를 검증했으며 에디터에서의 컴파일과 플레이는 라이선스가 활성화된 설치에서 별도 확인한다. 입력 요구와 한계는 각 `engines/<target>/README.md` 및 [웹 엔진 비교](engines/HTML-ENGINES.md)에 있다. 웹 결과는 HTTP로 제공해야 한다.


### 한국어 · 日本語

상단 언어 선택기로 작업실을 한국어 또는 일본어로 바꾼다. 주소의 `?lang=ja` 또는 `?lang=ko`가 가장 먼저 적용되며, 그다음에는 이 작업실 주소에서 저장한 언어, 브라우저의 지원 언어 순서를 따른다. 어느 쪽도 지정되지 않으면 한국어로 연다. 프로젝트와 함께 공유하려면 `?project=<등록된 ID>&lang=ja`처럼 두 값을 함께 지정한다. 언어 설정은 브라우저에 보관한다. 프로젝트 기획문·에셋 이름·기록된 원문과 JSON-LD는 원본 값을 표시한다.

画面右上の言語切り替えで「日本語」を選べます。日本語の画面を共有するには URL に `?lang=ja` を指定します。言語を切り替えても、表示中のシーン、選択したアセット、グラフの記録は維持されます。

첫 화면에서 프로젝트 그림을 선택해 장면과 에셋을 본다. 썸네일을 누르면 에셋 상세가 열리고, 파일 경로·해시·원문은 기술 정보에서 확인한다. 실행 기록과 기획/제작 단계는 필요할 때 펼친다. 등록된 프로젝트들에 장면이 있지만 현재 프로젝트에 빌드가 없으면 프로젝트 그림을 시작 화면에 보여 준다.

완료된 웹 게임으로 연결하려면 workspace manifest의 `playtests` 배열에 `{"activity":"<엔진 내보내기 ExternalWork ID>","url":"http://127.0.0.1:<게임 서버 포트>/<출력 폴더>/" }`를 추가한다. 별도 포트에서 그 정적 결과를 제공한다. 해당 실행의 runtime을 실제 입력으로 사용한 완료된 Three.js/Phaser 내보내기에만 **게임 열기 / ゲームを開く**가 표시된다. 링크 등록은 서버의 현재 가동 여부를 보장하지 않는다.

## PNG → Rive 캐릭터 (0.8.1)

방향 전환·공격·연기는 **상태별로 그린 PNG 프레임**을 기본으로 사용한다. 원화는 외형 정체성 기준이다. 원하는 방향과 몸의 형태가 달라지면 그 상태를 그린 뒤 원속도로 확인한다. 관절 컷아웃은 사용자가 명시적으로 원할 때만 임시 방법으로 사용한다.

`art/character.request.json`은 아래와 같다. `reference`는 선택적인 원화이며 프레임 자동 생성이나 외형 승인을 뜻하지 않는다.

```json
{"schema_version":1,"frames":"poses/frames.json","reference":"hero.png","actions":["idle","walk","attack"],"title":"숲의 로봇","language":"ko"}
```

`poses/frames.json`은 Rive pose manifest다. 예를 들어 `{"schema_version":1,"size":[64,64],"actions":{"idle":{"loop":true,"frames":[{"path":"idle-0.png","duration_ms":100}]}}}`다. 요청한 모든 상태가 manifest에 있어야 한다. PNG 경로는 manifest 폴더 기준이며, actions 순서와 각 프레임 시간·순서를 보존한다. 선택하지 않은 상태의 PNG는 읽거나 복사하지 않는다.

```sh
python3 tools/character.py --project "$PROJECT" \
  --request art/character.request.json --out characters/hero-1
```

`frames`, `source`, `motion_request`는 정확히 하나만 선언한다. `source`는 임시 자동 컷아웃, `motion_request`는 기존 승인된 master·명시적 rig·마스크의 motion 요청이다. `reference`는 frames 모드에서만 사용한다. 경로는 각 요청 폴더 안 상대 경로이며 symlink·hardlink 별칭을 거부한다. 요청과 manifest는 각각 1 MiB 이하, actions는 중복 없는 최대 32개 순서 목록, 선택 프레임은 총 256개, 중복을 제외한 소스 미디어 합계는 32 MiB 이하다.

기존 프로젝트 디렉터리에 그래프 ID가 없으면 정상 record 경로로 만든다. workspace manifest의 projects에 등록해 관찰한다. 새 출력의 `inputs/files/`에는 실행 요청·선택한 manifest·실제 소스 바이트가, `inputs/original-frames-manifest.json`에는 원본 manifest가, `bundle/`에는 `player.html`, `character.riv`와 제작기 진단이 남는다. stdout files의 경로는 프로젝트 기준이다. 입력은 관측 Artifact, 출력은 실제 해시와 used 관계를 가진 생성 Artifact로 기록한다. 제작 전후 원본과 실행 사본의 변경을 검사한다. `.game-studio` 안 출력은 거부한다.

ready는 기술 납품이며 외형 승인은 pending이다. 제작기의 needs_review 종료 코드 1을 정상 검토 상태로 받아 stdout JSON과 Studio 종료 코드 2로 진단을 반환한다. error는 stderr JSON과 종료 코드 2이며 생성된 부분 파일을 그래프에 기록한다. 기존 경로를 덮어쓰지 않는다. 실패나 검토 상태는 산출물을 확인하고 새 --out으로 재시도한다. 자체 포함 player.html의 실제 동작 재생과 사람의 외형 판단은 별도 검수다.
