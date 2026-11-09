# 직업별 전투를 첫 플레이에서 제작하기

빈 폴더에서 시작한다. 네 직업이 있는 **유리종탑의 결투**에는 배경, 캐릭터 자세, 프레임별 효과, 조준과 이동, 적 공격 예고, 피해·빗나감·받아치기와 재도전이 있다. 결과는 수정할 수 있는 독립 게임 소스다.

```sh
python3 "$STUDIO_ROOT/tools/web_game.py" --init-combat --project ./new-duel
python3 "$STUDIO_ROOT/tools/web_game.py" --project ./new-duel --out play/first
python3 -m http.server --bind 127.0.0.1 --directory ./new-duel/play/first 8300
```

## 새 직업의 원화와 명중 프레임 만들기

새 게임의 직업명이 정해졌다면 공격이 **어디서 시작해 어느 방향으로 나가며 언제 닿는지** 먼저 정한다. 검사의 사선 베기, 격투가의 지면 충격, 성술사의 낙하, 사수의 관통 사격은 실루엣과 접촉 시각이 다르다. 짧은 타격, 큰 기술, 적의 공격, 방어 성공, 허공에서 사라지는 공격을 같은 폭발로 대체하지 않는다.

```sh
python3 "$STUDIO_ROOT/tools/web_game.py" --init-combat --project ./new-choir \
  --combat-brief "$STUDIO_ROOT/starter/combat-brief/choir.json"
python3 "$STUDIO_ROOT/tools/web_game.py" --project ./new-choir --out play/first
```

이 예시는 공명기사와 시계궁수를 만들고 설치된 Pixel Asset Pipeline으로 직업마다 다른 명중 시트를 생성한다. 원화를 추가할 때는 프로젝트에서 만든 투명 PNG/WebP를 선택한다. 한 기술의 준비·이동·충돌·확산·소멸을 여섯 노출로 그려 3×2 정사각 셀에 배치한다. 예시의 황동 파문은 새로 그린 시트다. `--combat-brief`는 이미지를 자동으로 그리지 않는다.

브리프는 `schema_version:1`, `title`, `jobs` 배열로 구성된다. 직업별 `id`, `name`, `skill`, `motif`가 필수다. `motif`는 `blade`, `brawler`, `astral`, `rail` 중 하나로 기본 몸과 공격 궤적을 정한다. `sheet`에 브리프 옆의 로컬 상대 경로를 주면 직업 전용 그림을 복사한다. `palette`를 주면 바깥색에서 중심색 순서의 3~8색으로 실제 `pixel-asset effect` 제작을 실행한다. 생략하면 동봉된 시트를 쓴다. 같은 motif를 쓰는 직업도 서로 다른 그림과 충돌색을 가질 수 있다. 직업에 `clip`을 추가하면 로컬 Pixel effect-clip 요청 JSON을 읽어 원본 GIF, 권리 고지, phase별 선택 시간을 검증하고 새 시트를 제작한다. 큰 기술의 준비·비행·명중 시간도 그 출력에 맞춘다. `actor`는 직접 그린 포즈를 `tools/combat_motion.py`로 컴파일한 개별 캐릭터 JSON이다. 같은 폴더의 WebP 시트와 공통 피벗을 검증해 선택 화면과 전투에 넣는다. 생성 실패나 기존 프로젝트 경로에서는 결과를 덮어쓰지 않는다.

캐릭터 제작 요청은 `schema_version:1`, 공통 `cell`과 발 `pivot`, `kinds`를 갖는다. 종류별로 `body_height`, `frames`(id, path, foot, scale, duration_ms), `actions`(상태별 frame id 순서)를 작성한다. 대기·좌우 보폭·힘 모으기·방출·접촉 후 자세·회수·피격·회피를 별개의 원화로 준비한다. 예를 들어 `"windup":["draw","load"], "move":["contact-left","pass-left","contact-right","pass-right"]`처럼 실제 체중 이동 순서를 지정한다. 상대 파일은 요청 옆에 두고 `python3 "$STUDIO_ROOT/tools/combat_motion.py" --request poses.json --out ./new-motion`으로 제작한다. 이미 생성한 게임의 동작을 바꿀 때도 새 출력으로 제작해 개별 metadata와 WebP를 재사용한다.

## 움직임과 판정 연결

- 시전 시점에 조준 좌표를 고정한다. 무기나 배우의 동작은 준비와 발사로 나누고, 접촉 시각에 현재 적 좌표로 단 한 번 판정한다. 빗나가도 준비와 이동은 보인다.
- 명중 판정에서 체력, 적 피격 자세, 방향성 파편, 짧은 정지, 소리를 함께 시작한다. 멈춘 동안 양쪽 캐릭터와 효과의 시계도 멈춘다. 무음·동작 감소에서 공격 결과와 판정 시간은 같아야 한다.
- 새 캐릭터는 대기 그림을 늘리거나 회전시키는 대신, 무게를 뒤에 싣는 자세, 힘을 보내는 자세, 접촉 뒤 무게가 넘어간 자세, 회수와 피격을 그린다. 공통 발 피벗으로 Pixel 시트를 제작해 게임 크기에서 원속도로 본다. 효과의 프레임 시간과 캐릭터의 프레임 시간을 구분한다.
- 기존 GIF는 설치된 Pixel `effect-clip`으로 돌리고, 접촉 프레임이 있는 원본 액션 세트는 `action-set`으로 비교한다. 원본 GIF·LICENSE·NOTICE와 원본 프레임 선택을 보존한다. 작화 PNG를 Rive 상태 머신과 독립 플레이어로 검토하려면 `tools/character.py`의 `frames` 경로를 쓴다. 엔진 납품에 필요한 파일만 게임에 포함한다.
- 정상 입력에서 조기 피해가 없는지, 같은 기술이 한 번만 명중하는지, 적이 피하면 체력이 유지되는지, 받아치기 후 빈틈이 생기는지 본다. `web_revision.py check`로 모바일 배치와 컨트롤도 검사한다. 수정판은 `web_revision.py build`로 기존 납품과 분리한다. 기술 통과와 사람의 손맛·외형 채택은 별도다.

시트별 pixelfx 원본 리비전·MIT·NOTICE는 생성한 게임의 `game/fx/credits.json`에 함께 납품된다. [연출 사례](PLAYBOOK.md), [엔진 피드백 계약](FEEDBACK.md), [설치 기능 지도](CAPABILITIES.md)에서 목적에 맞는 제작기를 찾는다.


## 실제 동작 검수

공명기사의 원본 자세 시트와 `knight-motion.json`도 설치된다. `combat_motion.py --request "$STUDIO_ROOT/starter/combat-brief/knight-motion.json" --out ./motion-review`로 Pixel 시트부터 다시 만들 수 있다. 컴파일된 공명기사는 고유 원화 18장을 쓰고(걷기/달리기/도약 포함), 기본 직업은 같은 바닥 피벗을 유지한 원화를 공유한다. 파일 수와 자세 수는 원속도에서 무게와 호흡이 자연스럽다는 보증이 아니다.

```sh
python3 "$STUDIO_ROOT/tools/combat_review.py" --project ./new-choir --actor job-0 \
  --clip-index 0 --out reviews/knight
```

이 명령은 게임에서 쓰는 시트의 실제 RGBA 영역을 잘라 프레임을 복원한다. 큰 기술의 준비·비행·접촉 시각을 Rive 상태에 넣고, 걷기·달리기·점프·피격 원화가 모두 있으면 Pixel 액션 세트의 같은 접촉 프레임에 명중 클립을 넣는다. 검수 HTML, Rive 파일과 재생기, 타이밍 기록을 프로젝트 그래프에 남긴다. 해당 포즈가 없는 캐릭터에는 허위 상태를 추가하지 않는다. Rive 플레이어에서 몸의 무게 이동을 보고 실제 게임에서 적 이동·빗나감·반격까지 확인한다.

동일한 PNG도 상태에 따라 노출 시간이 달라진다. 예를 들어 대기에서는 900ms 유지하는 자세를 큰 기술 준비에서는 잠깐만 보일 수 있다. 동작 요청에 `"action_ms":{"heavy":[35,65],"recover":[140,60]}`를 주면 해당 상태의 두 자세가 그 **비율**로 실제 준비·회수 시간을 나눠 쓴다. 각 값은 1..60000ms 정수이며 상태 하나의 합은 60000ms 이하다. 지정하지 않은 상태는 기존 프레임 시간을 사용한다. Rive·액션 세트 검토도 같은 비율로 계산한다.

## 에셋 제작과 비교

새 프로젝트에는 직업별 원화·동작·기술 제작 지시서 `art-direction.md`가 생긴다. 전투 에셋은 [미술 제작 기준](ASSET-ART.md)에 따라 캐릭터, 초상화, 무대, 효과를 함께 검토한다.

```sh
python3 "$STUDIO_ROOT/tools/web_game.py" --project ./new-choir --review-assets
```

이 명령은 현재 소스와 설치된 공명기사 기준을 나란히 재생할 수 있는 **독립 HTML**, 실제 소스 해시·결함·수정 방법을 담은 JSON, 해당 판의 수정 지시서를 프로젝트의 새 `checks/asset-review-…` 폴더에 만든다. 기본 전투 생성 경로와 기존 0.14.x 전투 스타터는 정상 내보내기·수정판 내보내기에서도 이 검사를 수행한다. 기술적으로 부족한 자산은 게임 출력 전에 진단하며 부분 납품물을 만들지 않는다. 문제가 있는 소스는 수정할 수 있다. 결과의 `artistic_acceptance`는 사람이 판단할 영역으로 남는다. 비교판에서 발이 미끄러지는지, 무기와 적이 맞물리는지, 인물과 FX가 실제 배경에서 읽히는지도 본다. 임의로 다시 작성한 JS의 동작은 브라우저에서 직접 검증한다.

빙정사수 예시는 `--combat-brief "$STUDIO_ROOT/starter/combat-brief/falcon.json"`을 쓴다. 여섯 장의 새 원화를 준비 자세·날아가는 매·첫 파쇄·얼음 날개·분리된 조각·잔설 순으로 만들었다. 제작 시트와 명중 팔레트는 이 프로젝트의 실제 산출물로 복사된다.
