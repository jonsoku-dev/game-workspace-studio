---
name: game-studio
description: 게임 아이디어를 첫 플레이로 만들고, 로컬 2D·3D 제작·동작 수정·A/B 비교·검수·엔진 전달을 대화로 진행할 때 사용한다.
---

게임 목표·조작·씬·엔진 연결을 소유한다. 이 파일에서 상위 세 폴더가 `$STUDIO_ROOT`다. 픽셀은 설치된 `pixel-asset`, 모델은 `model-assets`의 계약으로 제작한다. 설치·의존성 문제는 [INSTALL](../../../INSTALL.md), 수정·검수 JSON과 증거 관계는 [GRAPH](../../../GRAPH.md)를 해당 단계에서 읽는다.

캐릭터 원화가 흐리거나 격자가 어긋나면 Pixel Asset Pipeline의 `snap`으로 입력·출력의 1× 비교판을 만든다. 팔·다리가 떨어진 정면 인물에는 `rig-draft`로 관절·마스크 초안을 만들고 원본 위에 겹쳐 확인한다. 이미 있는 마법 GIF는 `effect-clip`으로 원본 프레임 번호·단계·피벗·재생 시간을 기록한 뒤 `action-set`에 연결한다. 게임 로고·파비콘 요청은 [SVG 후보와 실제 크기 검수](../../../starter/identity/LOGO.md)를 사용한다.

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

사용자 원본을 선택하면 설치된 pixel-asset-pipeline 스킬의 `motion` 계약을 읽는다. `approved:true`, 로컬 `master`, 모든 불투명 픽셀의 겹치지 않는 부위·관절·부모 리그가 필요하다. 보이는 원본의 컷아웃 관절 애니메이션이며 숨은 신체나 새 시점을 그리지 않는다. `inspection.json`의 중립 복원·잘림·중복·접촉 오차와 원속도 실루엣·발 접지·루프를 함께 본다.

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
