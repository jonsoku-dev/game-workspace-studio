---
name: game-studio
description: 원화 PNG를 원하는 동작의 Rive 캐릭터로 만들거나 게임 아이디어를 첫 플레이로 만들고, 로컬 2D·3D 제작·동작 수정·A/B 비교·검수·엔진 전달을 대화로 진행할 때 사용한다.
---

게임 목표·조작·씬·엔진 연결을 소유한다. 이 파일에서 상위 세 폴더가 `$STUDIO_ROOT`다. 픽셀은 설치된 `pixel-asset`, 모델은 `model-assets`의 계약으로 제작한다. 설치·의존성 문제는 [INSTALL](../../../INSTALL.md), 수정·검수 JSON과 증거 관계는 [GRAPH](../../../GRAPH.md)를 해당 단계에서 읽는다.

캐릭터 원화가 흐리거나 격자가 어긋나면 Pixel Asset Pipeline의 `snap`으로 입력·출력의 1× 비교판을 만든다. 사용자가 관절 컷아웃을 명시적으로 선택한 경우에만, 팔·다리가 떨어진 정면 인물의 `rig-draft` 관절·마스크 초안을 원본 위에 겹쳐 확인한다. 이미 있는 마법 GIF는 `effect-clip`으로 원본 프레임 번호·단계·피벗·재생 시간을 기록한 뒤 `action-set`에 연결한다. 게임 로고·파비콘 요청은 [SVG 후보와 실제 크기 검수](../../../starter/identity/LOGO.md)를 사용한다.

## 원화와 상태별 작화에서 Rive 캐릭터까지

“원화로 걷기·공격 Rive를 만들어 줘”는 첫 플레이 게임 대신 이 경로를 사용한다. **방향 전환·연기·공격 실루엣은 각 상태에 맞춰 그린 PNG 프레임을 기본으로 권한다.** 원화는 캐릭터의 외형 기준으로 사용하고, 필요한 방향·표정·몸의 형태를 실제로 그린다. 사용자에게 거절된 관절 컷아웃을 기본 해결책으로 반복하지 않는다. 설치된 Pixel Asset Pipeline의 `character`·`rive` 계약을 읽고, 프레임의 크기·픽셀 스타일·정체성과 동작의 원속도 연결을 확인한다. 작화 완료와 사용자의 외형 승인을 구분한다.

요청은 `frames`, `source`, `motion_request` 중 정확히 하나를 선택한다. 기본 작화 경로는 `frames`로 Rive pose manifest를 가리킨다. `reference`는 선택적인 원화 PNG이며 외형 정체성 참조일 뿐, 포즈를 자동 생성하거나 승인하는 입력이 아니다. `actions`는 사용할 상태의 순서를 명시하며 선택한 상태의 PNG만 사용한다.

```json
{"schema_version":1,"frames":"poses/frames.json","reference":"hero.png","actions":["idle","walk","attack"],"title":"숲의 로봇","language":"ko"}
```

pose manifest는 `schema_version:1`, `size:[폭,높이]`, `actions:{"idle":{"loop":true,"frames":[{"path":"idle-0.png","duration_ms":100}]}}` 형식이다. PNG 경로는 manifest 폴더 기준이다. 요청·manifest는 각각 1 MiB 이하, 사용 상태는 최대 32개, 선택 프레임은 총 256개, 중복을 제외한 소스 미디어는 총 32 MiB 이하다. `source` 자동 컷아웃은 사용자가 그 방식을 명시적으로 원할 때만 임시 리그로 제안한다. 기존 승인된 관절 리그는 `motion_request`로 master·마스크를 포함한 motion 요청을 지정한다.

```sh
python3 "$STUDIO_ROOT/tools/character.py" --project "$PROJECT" \
  --request art/character.request.json --out characters/hero-1
```

프로젝트는 기존 디렉터리이며 필요하면 정상 그래프 기록이 프로젝트 ID를 만든다. workspace에 해당 프로젝트를 등록해 합쳐 읽는다. 출력은 새 프로젝트 상대 폴더만 허용하며 `.game-studio` 안에는 만들지 않는다. `inputs/files/`에 실제 요청·선택한 프레임·선택 manifest·참조 또는 motion과 마스크를 고정하고, `inputs/original-frames-manifest.json`에 원본 manifest를 보존한다. 선택하지 않은 PNG는 읽거나 복사하지 않는다. `bundle/`에 제작기 결과를 보존한다. symlink·hardlink 별칭과 루트 탈출은 거부한다.

stdout의 `files.player`와 `files.character`는 프로젝트 상대 자체 포함 HTML·Rive 경로다. `ready`는 기술 상태이고 외형 승인은 pending이다. 제작기의 `needs_review` 종료 코드 1은 정상 검토 상태로 받아 보존하며 Studio는 stdout JSON·종료 코드 2를 반환한다. error는 stderr JSON·종료 코드 2이며 부분 출력과 실패 그래프를 남긴다. 기존 출력은 보존하고 새 `--out`으로 재실행한다. 실제 전체 동작 재생과 사용자의 판단은 별도 검수다.

## 대화에서 첫 플레이까지

1. 사용자의 아이디어 원문·제목·목표·플레이어 행동·완료 기준을 정한다. 이미 정해진 내용은 다시 묻지 않는다. 기본 첫 슬라이스는 **이동 → 표적을 향한 유효 공격 N회 → 완료 → 재시작**이며 N은 1..20이다. 아이디어를 임의 게임 규칙으로 자동 해석하지 않는다. 지원 범위와 선택한 제약을 짧게 밝히고 새 프로젝트에 고정한다. 한국어는 `ko`, 일본어는 `ja`를 선택한다.

```sh
python3 "$STUDIO_ROOT/tools/start.py" new "$PROJECT" \
  --idea "숲의 로봇이 표적을 향해 이동해 세 번 명중하는 훈련" \
  --title "숲 로봇 도장" --language ko --hits 3
python3 "$STUDIO_ROOT/tools/start.py" build "$PROJECT"
```

2. `new`는 새 폴더에만 원자적으로 작성한다. 포함된 원본 CC0 로봇·명시적 리그를 사용하므로 첫 사용에 이미지 파일을 따로 만들 필요가 없다. `build`는 로컬 `pixel-asset motion` → `action-set` → Studio → 그래프에 등록된 Phaser 납품을 실행한다. 설치된 CLI에 `motion`이 있고 고정 Phaser 의존성이 준비돼 있어야 한다. 출력의 실제 서버 명령을 실행하고 주소를 연다. `playable_export`는 파일 준비 상태다.
3. 재개할 때 `start.py inspect "$PROJECT"` 또는 `resume`/`status`를 실행하고 실제 다음 명령을 따른다. 변경·부분 산출물은 먼저 검사한다. 기존 출력을 덮어쓰거나 실패를 숨겨 자동 재시도하지 않는다. 첫 3D 장면은 `new ... --kind 3d`와 `build`로 등불·불티를 만들고 출력된 visualizer 명령을 실행한다. 이 경로는 관찰용 장면이다.
4. 새 Phaser 납품을 정상 조작으로 검증한다. 아래 `play/run-...`은 출력에서 확인한 프로젝트 상대 경로로 바꾼다. 명령은 임시 로컬 서버와 설정된 Stagehand MCP를 사용하고 검사 후 서버를 닫는다.

```sh
python3 "$STUDIO_ROOT/tools/playcheck.py" run \
  --project "$PROJECT" --export play/run-...
```

브라우저를 실행하지 못하면 그 범위를 미검증으로 남긴다. `playcheck.py --observations ...`는 기존 관측의 검산 도구이며 `run`의 독립 브라우저 실행을 대신하지 않는다. 파일 생성, 기술 검사, 실제 플레이, 사람의 외형 승인을 구분해 보고한다.

## 원본과 동작 수정

기존 관절 컷아웃의 동작 수정을 명시적으로 선택하면 설치된 pixel-asset-pipeline 스킬의 `motion` 계약을 읽는다. `approved:true`, 로컬 `master`, 모든 불투명 픽셀의 겹치지 않는 부위·관절·부모 리그가 필요하다. 보이는 원본의 컷아웃 관절 애니메이션이며 숨은 신체나 새 시점을 그리지 않는다. `inspection.json`의 중립 복원·잘림·중복·접촉 오차와 원속도 실루엣·발 접지·루프를 함께 본다.

```sh
pixel-asset motion --request "$PROJECT/requests/motion.json" --out "$PROJECT/requests/motion-new"
```

독립 제작은 실제 사용한 입력과 생성 파일을 `graph.py record`로 연결한다. 나온 `action-set.request.json`을 `pixel-action-set` 씬 에셋 요청으로 선택하고 노드에 `action`, `size_m`를 둔다. 외부 효과는 선택 사항이며 no-FX Phaser는 `scene.playtest.contact_frame`과 `at_px`로 접촉을 고정한다.

기존 ready A의 동작 수정은 같은 프로젝트에서 새 B로 만든다. [GRAPH의 수정 계약](../../../GRAPH.md#동작-수정과-ab-검수)을 읽고 패치를 작성한다. 프레임 순서·시간·교체 PNG·앵커 및 효과/접촉 프레임 매핑을 명시한다. 결함이 있는 동작만 바꾸고 A를 보존한다.

```sh
python3 "$STUDIO_ROOT/tools/revise.py" --project "$PROJECT" \
  --base "$RUN_A" --asset hero --patch "$PATCH" --out revisions/b-1 --build
```

출력의 B run ID·실제 diff·원속도 GIF·접촉 시트를 확인한다. 새 B를 엔진에 납품하고 브라우저 검사를 다시 실행한다. A/B를 비교할 때 `review.py compare/check/choose --project ... --record ...`를 사용한다. 기술 통과만 있으면 `technical-pass`; 사람의 실제 시각 판단과 필수 gameplay 근거가 모두 통과해야 `adopt`다. 사용자 판단을 대신 작성하지 않는다. 수정 요청은 `request-changes`; 활성 채택은 `review.py resolve`로 읽는다. 실패·pending을 해결할 때 새 증거와 명시적 supersession 사유를 남긴다.

## 기존 씬과 관찰

기존 프로젝트는 기획·씬·엔진 제한을 먼저 읽고 정상 진입점으로 검증·제작한다.

```sh
python3 "$STUDIO_ROOT/tools/scene.py" validate --project "$PROJECT"
python3 "$STUDIO_ROOT/tools/scene.py" build --project "$PROJECT" --out build/run-new
```

씬은 미터·+Y 위·오른손 좌표, 회전은 XYZ 도 단위다. 픽셀 `size_m`는 scale 전 정사각형 폭이다. 3D 소품 효과는 model-assets의 메시 효과를 사용하며 Forest Camp 불티는 등불의 `parent`로 부착한다. 배치만 바꿀 때는 성공 실행의 `reuse:{run_id,asset}`를 선택한다. 일반 납품은 `export_game.py --engine <godot|three|phaser|unity> --project <등록된 프로젝트> --workspace <workspace.json> --source <등록된 프로젝트> <ready runtime> --out <새 상대경로>`다. 타깃별 지원 범위는 [엔진 문서](../../../engines/HTML-ENGINES.md)를 따른다.

이력·에셋·씬·A/B 비교는 `visualize.py --project "$PROJECT"`로 읽는다. 등록 workspace를 볼 때만 `--workspace ... --browse-workspace`를 추가한다. 화면은 읽기 전용이며 제작·수정·판정은 이 채팅에서 수행한다. 한국어 링크는 `lang=ko`, 일본어는 `lang=ja`; 기존 project 쿼리는 유지한다. 모든 제작·개발·검증은 프로젝트 그래프에 실제 사용·생성·관찰 관계로 연결한다. 배포·구매·기존 파일 삭제 등은 사용자의 명시적 권한 범위를 따른다.
