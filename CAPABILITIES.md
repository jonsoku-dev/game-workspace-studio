# 설치 기능 지도

게임을 제작하기 전에 목표·원본·납품 엔진을 보고 아래 도구를 고른다. **새 2D 직업 액션**의 기본 흐름은 작화 → 캐릭터 시트·공격 효과 → 게임 입력·접촉 → 수정판 비교 → 설치본 브라우저 플레이이다. 아래의 다른 납품 엔진, 3D 소품, 관절 리그에는 각각 다른 입력이 필요하다.

| Studio 진입점 | 쓰는 경우 |
| --- | --- |
| `start.py new/status/inspect/resume/build` | 등록 프로젝트의 첫 2D 타격/배달 또는 3D 관찰 씬, 중간 상태 복구. |
| `web_game.py --init-combat/--init-campaign/--out` | 직업 전투, 여러 판 캠페인, 기존 독립 웹게임 납품. 소스·런타임 해시를 기록한다. |
| `web_game.py --review-assets` | 공명기사 기준과 실제 프로젝트 원화·자세·효과를 비교하고 부족한 셀에 대한 수정 지시를 기록한다. |
| `combat_motion.py` | 직접 그린 여러 자세를 Pixel 시트로 제작해 같은 발 피벗과 단계별 시간으로 전투에 적용. |
| `combat_review.py` | 게임의 실제 캐릭터 시트와 직업별 접촉 시간으로 Rive 재생기와 액션 세트의 명중 동작을 원속도 검토. |
| `scene.py validate/build` | 선언형 씬의 pixel-effect, pixel-action-set, model-assets 배치 및 실제 제작기 실행. |
| `character.py` | 작화 프레임·승인 리그·원화 중 하나에서 Rive 캐릭터, 원본 핀과 독립 플레이어 제작. |
| `web_revision.py diff/build/check` | 기존 웹 납품의 변경판·회귀·모바일 레이아웃, 수정 전과 수정 후 같은 입력의 관측. |
| `reference_review.py inventory/review` | 새 첨부 원본, 적용 근거와 누락·변경 확인. |
| `revise.py`, `review.py compare/check/choose/resolve` | 등록된 씬의 프레임·피벗·접촉 매핑 수정과 A/B 검수. 독립 웹게임 수정은 web_revision을 사용. |
| `playcheck.py run`, `playcheck_browser.py` | 실제 Phaser 내보내기 조작. 이전 관측 JSON 검산과 구별한다. |
| `export_game.py --engine godot/three/phaser/unity` | 등록된 ready 씬을 선택 엔진으로 내보냄. 독립 Canvas 게임을 이 명령으로 변환하지 않는다. |
| `graph.py record/query/export/history`, `workspace_graph.py`, `visualize.py` | 원본·실행·검증 기록, 프로젝트 그래프 합치기, 읽기 전용 검수. |
| `install_workspace.py` | 격리된 환경·로컬 패키지 설치. 소스 저장소의 `stage.py`는 배포 제작용이다. |

## Pixel Asset Pipeline

| 명령 | 제작에 쓰는 입력과 결과 |
| --- | --- |
| `build/validate` | 픽셀 초안과 정적 PNG 제작·검사. |
| `variant/compare/tile` | 장비 변형, 정적 자산 세트 비교, 타일 반복과 이음새. |
| `sheet` | 동일 셀로 직접 작화한 포즈와 시간·피벗을 보존하는 시트. |
| `action-set` | 대기·걷기·달리기·공격·점프·피격의 시트와 실제 접촉 프레임 FX. |
| `effect` | step/land/slash/impact/confirm/deny/pickup/flame을 색상·시드·시간·피벗과 함께 제작. |
| `effect-clip` | 기존 GIF의 원본 프레임을 charge/travel/impact로 배치. 원본 고지 동봉. |
| `snap/rig-draft/motion` | 픽셀 격자 보정, 분리된 인물의 관절 초안, 사용자가 선택한 승인 컷아웃 리그의 동작. |
| `character/rive` | 작화 PNG를 선택 가능한 Rive 상태와 자체 포함 HTML 플레이어로 제작. |

## Model Assets와 엔진

Model Assets의 `build.py`는 Blender의 등불·불티 또는 로컬 정적 .blend 메시를 GLB로 제작·검사한다. `serve.py`는 그 번들을 WebGL로 미리 본다. Three와 Godot·Unity의 3D 장면, Phaser·Godot의 2D 액션 세트, 독립 Canvas의 프레임 시트는 서로 다른 제작 경로다. [엔진 계약](engines/HTML-ENGINES.md)과 각 제작기의 스킬에서 입력 제한을 확인한다. 기술적으로 내보낸 상태를 사람의 외형 승인으로 기록하지 않는다.
