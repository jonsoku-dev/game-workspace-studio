---
name: game-studio
description: 게임 목표와 조작을 기획하고 씬의 소품·효과 배치를 작성하거나 설치된 2D·3D 제작기를 게임 프로젝트에 통합할 때 사용한다.
---

게임 목표·조작·씬 배치·엔진 연결을 소유한다. 픽셀 제작은 설치된 pixel-asset-pipeline에, 모델 제작은 설치된 model-assets에 맡긴다. 제작기 코드를 복사하거나 별도 API·외부 서버·공급자 폴백을 추가하지 않는다.

1. 사용자가 지정한 게임 프로젝트의 기획과 엔진을 읽는다. `scene.json`에 목표·조작과 이름 있는 소품·효과를 배치한다. 새 프로젝트는 [예시](../../../examples/forest-camp/scene.json)의 구조로 시작한다.
2. 각 에셋의 프로젝트 상대 요청 JSON을 작성한다. `pixel-effect`는 설치된 `pixel-asset effect`를, `model-assets`는 활성 설치본의 `tools/build.py`를 호출한다. 다른 제작 행동은 설치된 해당 스킬의 계약을 먼저 읽는다.
3. 이 스킬 파일에서 상위 세 폴더가 플러그인 루트다. 아래 경로를 실제 값으로 바꿔 실행한다.

```sh
python3 "$PLUGIN_ROOT/tools/scene.py" validate --project "$PROJECT"
python3 "$PLUGIN_ROOT/tools/scene.py" build --project "$PROJECT" --out build/run-1
```

4. 실패 원인을 고친 뒤 새 `--out`으로 재실행한다. 기존 출력 덮어쓰기나 자동 재시도를 하지 않는다. 성공한 `scene.runtime.json`의 모든 파일 경로는 프로젝트 루트 기준이다.
5. 엔진에는 3D `model` GLB와 메타데이터를, 2D `sheet` PNG와 `metadata`의 프레임·시간·피벗을 연결한다. 씬은 미터 단위·+Y 위쪽·오른손 좌표다. 회전은 도 단위 XYZ Euler다. 픽셀 노드의 `size_m`는 scale 적용 전 정사각형 폭이다. 엔진 좌표가 다르면 어댑터에서 변환한다.
6. 실제 엔진에서 모델 배치와 효과 재생을 확인한다. 구조 검증, 제작기 통과, 시각 검토, 실제 플레이 검증을 구분해 보고한다. ready는 파일 납품 상태다.

경로·실패·스테이징 계약은 [README](../../../README.md)를 읽는다. 사용자 승인 없는 설치·배포·구매·기존 파일 삭제는 이 스킬의 범위가 아니다.

모든 제작 작업을 프로젝트 SSOT 그래프에 연결한다. 일반 씬 제작은 자동 기록된다. 독립 모델 제작·기획 결정·외관 검토·검증처럼 씬 빌드를 거치지 않는 작업은 [그래프 계약](../../../GRAPH.md)의 `record` 명령으로 등록한다. 입력으로 사용, 직접 관찰, 생성, 실패의 관계를 실제 근거에 맞게 선택한다. 실행 순서만으로 원인을 추정하지 않는다.

사용자가 히스토리·에셋·씬을 보고 싶으면 `python3 "$PLUGIN_ROOT/tools/visualize.py" --project "$PROJECT"`를 실행하고 출력 주소를 제공한다. 등록된 workspace가 있으면 `--workspace "$WORKSPACE/workspace.json"`를 추가한다. visualizer는 읽기 전용이며 새 제작·수정은 이 채팅의 명령으로 실행한다.

3D 소품의 효과는 기본적으로 `model-assets`의 실제 메시 효과를 사용한다. Forest Camp의 불티는 등불을 `parent`로 참조한다. 2D 시트는 2D 씬 또는 브리프에서 혼합 표현을 선택했을 때 배치한다. 물체와 효과가 함께 움직이는지, 앞·뒤의 불티가 같은 깊이에서 올바르게 가려지는지 실제 씬에서 확인한다.

로컬 캐릭터 6동작과 pixelfx 접촉 효과는 `pixel-action-set`으로 요청한다. 노드에는 `action`과 `size_m`를 기록한다. 프레임·효과 시트·고지의 출처는 요청 폴더 아래에 보존하고 SSOT 그래프의 입력 리비전과 실제 제작 산출물을 확인한다.

배치만 변경할 때는 앞선 성공 실행의 모델이나 시트를 `{"id":"prop","producer":"model-assets","reuse":{"run_id":"<기존 run_id>","asset":"<기존 asset id>"}}`로 선택한다. 요청과 reuse 중 한 가지만 둔다. 제작기는 호출하지 않으며 원본 파일 해시가 달라지면 재사용이 실패한다. 외부 작업이 만든 산출물은 원본 SHA-256과 실제 사용한 입력을 generated 필드로 등록하고, 단순 관찰과 구분한다. 엔진 통합 후 실제 입력·판정·재시작과 엔진 영수증을 해당 그래프에 남긴다.

워크스페이스의 등록된 프로젝트 사이를 이동할 때만 `--browse-workspace`를 지정한다. 화면의 동작·회전·정지 선택은 검수용이며 기록된 입력과 그래프를 수정하지 않는다. Godot 4 샘플은 `$PLUGIN_ROOT/engines/godot/export.py --source <project> <runtime> --source <project> <runtime> --output <new-folder>`로 준비한다. 등불·불티와 scout 동작 세트를 각각 주고, 어댑터 README의 실제 입력 검사를 따른다. 이 샘플의 고정된 게임 규칙을 임의의 사용자 게임에 자동 이식했다고 보고하지 않는다.
