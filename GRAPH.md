# 실행 이력 그래프

프로젝트의 `.game-studio/project.json`이 UUID 식별자를 보관한다. 파일과
`.game-studio/runs/*.jsonld`를 함께 복사하면 경로가 달라져도 식별자와 해시는 유지된다.
새 프로젝트에는 새 UUID를 사용한다. 프로젝트 디렉터리 이름은 식별자가 아니다.

실행별 JSON-LD 샤드가 이력의 원본이다. 별도의 쓰기 가능한 이력 데이터베이스는 없다.
`history()`와 시각화 화면은 이 샤드에서 계산한 읽기 전용 투영이다. 내보내기는 프로젝트를
만들거나 파일을 변경하지 않는다. 서로 다른 실행은 서로 다른 샤드를 쓴다. 임시 파일에
쓴 뒤 원자적으로 교체하며, 외부 작업 기록은 기존 샤드를 덮어쓰지 않는다.
한 실행의 진행 상태를 갱신하는 작성자는 하나여야 한다.

## 스키마와 인과 관계

`graph.py`의 `CONTEXT`는 버전 1의 인라인 JSON-LD 1.1 컨텍스트다. 네트워크 조회가
필요하지 않으며, 네임스페이스는 `https://game-studio.local/ns/v1#`이다.
기존 0.1.x 실행의 v1 컨텍스트와 `attachedTo`를 추가한 v1 컨텍스트를 모두 읽는다.
내보내기는 현재 컨텍스트를 사용하지만 기존 샤드나 식별자는 변경하지 않는다.
기존 용어를 재정의하거나 알 수 없는 컨텍스트로 바꾸는 것은 거절한다.
PROV-O의 Entity, Activity, Agent, used, wasGeneratedBy, wasDerivedFrom,
wasAssociatedWith를 사용한다. 프로젝트 전용 타입은 같은 컨텍스트에 있다.
JSON 사본·실행 기록·검사 목록은 `@json` 리터럴이므로 내부 키가 그래프 관계로 해석되지 않는다.

- Project → Game → SceneRevision은 프로젝트·게임·내용으로 고정한 씬 입력이다.
- RequestRevision은 원본 경로, 요청 내용 해시, 소스 입력의 해시로 식별한다.
  동일한 JSON 요청이라도 `source_blend`가 변경되면 다른 입력 리비전이다.
- ExecutedRequest는 실제 제작기에 전달한 요청 사본이다. 원본 RequestRevision과
  사용한 SourceArtifact에서 유래하며, WorkStep의 `used`가 이를 가리킨다.
- Run은 실행이며 RunRevision은 실행 상태가 갱신될 때 보존하는 JSON 사본이다.
  실행 중 같은 메모리 레코드를 계속 전달한다. RunRevision의 `sequence`는 상태 기록
  순서이며 작업 간 인과 관계를 주장하지 않는다.
- Plugin은 제작기의 에이전트다. 구현 지문이 있으면 정규 JSON의 SHA-256으로 ID를
  구분하고 `implementation` JSON 리터럴에 버전·코드 해시를 보존한다. Studio 실행기도
  같은 방식으로 Run과 연결한다. 지문 없는 기존 기록은 이름 기반 ID를 유지한다.
  WorkStep은 실제 시작된 작업만 나타낸다.
  `pending` 상태만 있는 작업은 실행된 Activity로 만들지 않는다.
- Artifact는 실제 관측한 산출물의 프로젝트 상대 경로·SHA-256·바이트 수를 기록한다.
  생성한 작업과 사용한 요청을 연결한다. 이미지·GLB·blend 등의 바이너리를 그래프에 복제하지 않는다.
- Validation은 실제 수행한 검사이며 `used`는 검사한 산출물이다.
  ValidationEvidence는 해당 검사의 결과다. 성공한 제작과 검사의 성공은 별도 사실이다.
- 모델 제작기의 메타데이터와 Webstage receipt, Three 검사 보고서가 계약과 일치하면
  Blender → raw GLB → Webstage → compiled GLB → Three 검사 관계를 기록한다.
  이 내부 단계에는 `evidenceBasis: producer-report`를 붙인다. 독립 재실행이나 시각적
  품질 검증을 의미하지 않는다. 보고서가 증명하지 않는 내부 단계는 추가하지 않는다.
- RuntimeProduct는 실제 생성된 런타임 문서이며 씬과 채택 산출물에서 유래한다.
  ScenePlacement는 실행별 배치 사본이며 사용한 산출물과 연결한다. 2D 효과는
  sheet·metadata, 모델은 compiled GLB를 가리킨다. mesh-particles 효과는 GLB와
  effect.json 레시피를 함께 가리킨다. `parent`가 있는 배치는 같은 실행의 부모 배치에
  `attachedTo`로 연결한다. 이것은 공간 부착 관계이며 실행 순서나 생성 원인이 아니다.
- MotionRecipe는 effect.json 산출물의 추가 타입이다. 경로·해시·크기와 함께
  JSON 레시피 전체를 `snapshot` 리터럴로 고정한다. 후에 파일이 바뀌어도 해당 실행에서
  관측한 파라미터를 읽을 수 있다. 효과 레시피의 실제 검사는 Validation으로 따로 기록한다.
- Error는 실패한 실행 또는 작업과 `failedWith`로 연결한다.
  입력이 거절된 실행에는 안전한 UnadmittedInput과 오류만 기록할 수 있다.

`dependsOn`은 선행 작업 의존성, `observed`는 관측 대상, `used`는 실제 입력 사용이다.
단순히 나중에 실행했거나 파일이 존재한다는 이유로 사용·생성을 주장하지 않는다.
`includesProject`는 워크스페이스 그래프의 명시적 프로젝트 소속 관계다.
이 구현은 OWL 추론기나 변경 불가능한 보안 감사 저장소가 아니다.

## Python API

```python
import graph

# scene 실행기가 소유하는 같은 레코드를 실행 내내 전달한다.
path = graph.update_run(project, record, scene)
document = graph.export_graph(project)  # @context, schema_version, @graph
records = graph.history(project)        # 공개 실행 기록 + graph_id, 시간/실행 ID 순
nodes = graph.query(project, subject=None, kind="Artifact")
```

`record.assets`에는 검증 후의 `{id, files: {role: project_relative_path}}`를 넣는다.
`record.steps`에는 asset, producer, status와 실제 검증한 경우에만
`validation: {passed, checks}`를 넣는다. `step.request`는 실제 실행 요청의 경로다.
런타임이 만들어진 뒤에만 `record.runtime`을 넣는다.

씬 에셋의 `reuse: {run_id, asset}`는 같은 프로젝트의 성공한 기존 실행을 선택한다.
`run_id`에는 실행 ID 또는 정확한 Run 그래프 ID를 쓴다. 실행기는 원래 파일의 경로·해시·크기와
번들 계약을 확인하며 요청 고정·제작기 호출·산출물 복사를 하지 않는다. 공개 레코드의 해당
asset과 step에는 `reuse: {run_id, asset, run, artifacts}`가 들어간다. `run`은 선택한 Run ID,
`artifacts`는 원래 Artifact ID 목록이며 step 상태는 `reused`다. 그래프도 이 ID와 실제 파일을
다시 확인한다. 재사용 WorkStep은 원래 실행과 산출물을 `used`로 가리키며 생성 관계를 붙이지
않는다. ScenePlacement와 RuntimeProduct는 원래 산출물에서 유래한다. 재사용을 다시
재사용해도 Artifact ID는 최초 생성 기록을 유지한다. 재사용 검사는 별도 Validation이다.
이전 파일이 바뀌거나 없어지면 새 실행은 실패하며 이전 샤드는 변경하지 않는다.

최초 갱신에서 `_graph_inputs`에 씬 JSON 사본과 요청 바이트를 고정한다.
제작기는 이 고정된 요청을 사용하며, 참조한 blend 소스를 복사할 때 해시와 크기를 확인한다.
`_graph_*`는 실행 내 메모리 상태이며 공개 history 투영에 나오지 않는다.
입력 JSON 사본은 그래프에 남으므로 요청에 비밀값을 넣지 않는다.
산출물은 최초 관측 시 해시를 고정하며, 나중에 원본 파일이 바뀌어도 이전 실행 해시를
다시 쓰지 않는다. 예전 파일의 실제 바이트 보존은 실행 산출물 디렉터리의 책임이다.

## 조회와 추가 작업 연결

```sh
python3 tools/graph.py export --project examples/forest-camp
python3 tools/graph.py history --project examples/forest-camp
python3 tools/graph.py query --project examples/forest-camp --type RuntimeProduct
python3 tools/graph.py query --project examples/forest-camp --id 'urn:game-studio:UUID:run:RUN_ID'
python3 tools/graph.py record --project . --record work.json
```

외부 검증·개발 작업도 작은 타입 레코드로 연결할 수 있다. 예를 들어 `work.json`:

```json
{
  "id": "inspect-runtime-1",
  "label": "Inspect runtime output",
  "agent": "local-reviewer",
  "status": "complete",
  "observed": ["urn:game-studio:UUID:run:RUN_ID"],
  "used": [],
  "files": ["evidence/runtime-check.json"],
  "generated": [],
  "verification": {"passed": true, "checks": ["Observed runtime check report"]},
  "references": ["https://example.org/source"]
}
```

`observed`와 `used`의 ID는 이미 해당 프로젝트 그래프에 존재해야 한다. 그래프를 조회해서
실제 ID를 사용한다. 임의의 외부 subject나 `@id`를 주입할 수 없다. `files`는 관측 파일이며
작업이 그 파일을 생성했다고 주장하지 않는다. 독립 제작·코드 변경 등의 실제 산출물은
`generated: [{"path": "deliverables/v2.json", "sha256": "<실제 SHA-256>",
"wasDerivedFrom": ["<사용한 기존 Entity ID>"]}]`로 명시한다. 해시가 실제 파일과 일치해야
등록되며 해당 Artifact만 외부 작업의 `wasGeneratedBy`를 가진다. 생성 선언은 제출자의
귀속 주장이고 명령이 제작 과정을 직접 관측했다는 뜻은 아니다. `wasDerivedFrom`은 선택
사항이며, 명시한 `used`에 포함된 기존 Entity만 허용한다. `used` 전체나 `observed`에서
파생 관계를 자동 추론하지 않는다. 같은 파일의 새 버전은 새 작업 ID로 등록하며 각 작업의
Artifact ID와 해시를 보존한다. 관측/생성 목록 간 동일 파일의 중복 선언은 거절한다.
verification은 제출자가 보고한 검사 결과이며,
이 명령 자체가 검사를 실행하지 않는다. references는 HTTPS 인용 문자열이다.
출처 링크만으로 인과 관계를 만들지 않는다. 외부 작업의 `recordedAt`은 그래프에
등록한 시각이며, 작업의 실행 시각이나 인과 관계를 주장하지 않는다. 같은 작업 ID 재등록, 프로젝트 밖 경로,
symlink 탈출, 알 수 없는 필드는 거절한다.
그래프 검증은 중복 ID·관계와 인과 관계 및 공간 부착의 순환도 거절한다.

```sh
python3 -m unittest discover -s tests -v
```

테스트는 입력 고정, 변경된 blend 소스 리비전, 관측과 생성의 구분, 보고서 기반 모델 관계,
누락된 참조·외부 subject 거절, 실패 이력, 동시 실행, 같은 씬 반복, 오프라인 복사와 읽기 전용
조회를 검사한다. 실제 제작기 및 브라우저의 검증 증거는 각 실행 기록과 별도로 판단한다.

3D 효과 회귀검사는 기존 2D 실행 샤드를 이전 컨텍스트 그대로 남긴 상태에서
부모 부착과 모델·MotionRecipe를 가진 새 실행을 함께 내보낸다. 레시피가 나중에
바뀌어도 이전 JSON 사본이 유지되는지, 누락된 부모 참조가 거절되는지도 검사한다.

## 로컬 2D 액션 세트

`pixel-action-set`의 원본 요청에 선언된 `actions.*.frames[].path`와
`events[].sheet`, `metadata`, `license`, `notice`만 입력으로 고정한다.
각 경로는 요청 파일의 부모 디렉터리 아래에 있어야 하며, symlink로 이 경계를
벗어나는 경로도 거절한다. 같은 파일을 여러 액션이나 이벤트가 사용하면 한 번만
기록한다. 선언하지 않은 폴더 전체나 다른 파일을 수집하지 않는다.

입력의 경로·SHA-256·바이트 수가 RequestRevision의 정체성에 포함된다.
같은 요청 JSON에서 PNG·효과 메타데이터·라이선스·NOTICE가 바뀌어도 새 리비전이 된다.
요청 JSON만 바이트 사본을 남기고 이 입력 파일들은 그래프에 복제하지 않는다.
Scene 실행기는 고정된 입력을 복사하고 해시·크기를 검사한 뒤 같은 상대 경로의
실행 요청으로 제작기를 호출한다. 파일이 그 사이 바뀌면 예전 입력으로 실행했다고
주장하지 않고 실패시킨다.

입력은 `SourceArtifact`와 `Imported2DInput` 타입이며 생성 활동을 붙이지 않는다.
WorkStep은 실제 사용한 입력과 ExecutedRequest를 가리킨다. 생성된 아틀라스와
재생 메타데이터는 `ActionAtlas`, `ActionMetadata` 산출물이다. 복사된 효과 파일은
`CopiedEffectInput`이며 내용 해시가 같은 원본 입력에서 유래한다. 이 관계는 로컬
가져오기·패킹 작업을 표현한다. AI 생성이나 Forge 제작 이력을 추정하지 않는다.

ScenePlacement는 런타임이 소비하는 `atlas`, `metadata`, `effect_N_sheet`,
`effect_N_metadata` 산출물을 가리킨다. 원본 포즈 PNG나 라이선스는 배치 대상으로
연결하지 않는다. 액션 시간·트리거·원점은 생성된 metadata 파일의 해시와 경로로
참조하며 그래프에 중복 사본을 만들지 않는다. 이 확장은 기존 컨텍스트와 실행 ID를
변경하지 않는다.

## 워크스페이스 연결

`workspace_graph.py workspace.json`은 명시적으로 등록한 프로젝트만 읽어 단일 JSON-LD 그래프를 만든다. `projects`의 경로는 manifest 디렉터리 안에 있어야 한다. `links`에 등록한 `{"activity":"<외부 작업 ID>","observed":"<관찰 대상 ID>"}`는 서로 다른 프로젝트 사이에서 확인한 관찰을 연결한다. 어느 한쪽 ID가 없으면 내보내기가 실패한다. 원본 실행 샤드는 그대로 보존된다.

엔진 내보내기처럼 다른 프로젝트 산출물을 실제 입력으로 읽은 작업은 `{"activity":"<외부 작업 ID>","used":"<입력 Entity ID>"}`로 연결한다. used와 observed 중 하나만 선언한다. 파일이 존재한다는 사실만으로 used를 추가하지 않는다. 내보내기는 의미가 맞지 않거나 순환하는 연결을 거부한다.

엔진 CLI가 여러 등록 프로젝트의 런타임을 소비하면 `workspace_inputs`에는 실제 내보내기 영수증에 남은 원본 Entity의 ID·SHA-256·바이트 수를 보존한다. 개별 프로젝트에서는 snapshot의 JSON으로 보관하며, workspace 내보내기는 양쪽이 존재하고 해시·크기가 일치할 때 해당 작업의 `used` 관계로 해석한다. 엔진 파일 생성 성공, 브라우저/엔진 실행, 직접 관찰은 각기 다른 증거다.

## 동작 수정과 A/B 검수

0.7.0의 시작·수정·검수는 기존 JSON-LD 샤드를 보존한다. `start.py new`는 첫 아이디어 원문·제목·제약·조작·측정 가능한 완료 기준과 포함된 원본을 새 프로젝트에 고정한다. `build`는 motion의 실제 입력·산출물을 외부 작업으로 연결한 뒤 정상 씬 제작과 등록 엔진 납품을 수행한다. 기본 2D는 `land_hits` 훈련이며 `hits_to_win` 1..20, no-FX의 `contact_frame`은 0부터 시작하는 공격 프레임, `at_px`는 셀 왼쪽 위 기준 접촉점이다. `scene.playtest`는 내용으로 고정한 SceneRevision과 RuntimeProduct를 통해 엔진에 전달된다. 첫 3D 템플릿은 등불·불티의 관찰용 장면이다.

`pixel-asset motion --request ... --out <새 폴더>`는 승인된 master와 명시적 rig에서 보이는 부위를 관절로 움직인다. 출력 `inspection.json`의 기술 통과와 외형 승인은 별개다. 독립 호출에서는 실제 읽은 master·rig의 기존 Entity를 `used`, 생성한 포즈·요청·검사 파일을 `generated`로 기록한다. 시작 도구는 이 연결을 수행한다. 이후 action-set은 생성 포즈를 입력으로 고정하며 원본을 다시 그렸거나 AI로 생성했다고 주장하지 않는다.

### A를 보존한 B 제작

```sh
python3 "$STUDIO_ROOT/tools/revise.py" --project "$PROJECT" \
  --base "$RUN_A" --asset hero --patch "$PATCH" --out revisions/b-1 --build
```

`base`는 같은 프로젝트의 정확한 ready run ID이며 `asset`은 그 실행의 에셋 ID다. `out`은 새 프로젝트 상대 폴더다. 패치는 JSON `{"schema_version":1,"actions":{...}}`이며 선택한 동작의 **전체 새 프레임 순서**를 쓴다. 예를 들어 기존 공격이 5프레임인 no-FX 스타터에서 첫 프레임을 80ms로 줄이는 패치:

```json
{
  "schema_version": 1,
  "actions": {
    "attack": {
      "frames": [
        {"source": 0, "duration_ms": 80},
        {"source": 1}, {"source": 2}, {"source": 3}, {"source": 4}
      ],
      "event_frames": {},
      "contact_frame": 2
    }
  }
}
```

`source`는 A의 0기반 프레임이다. 순서 변경·삭제는 이 목록으로 표현한다. 교체는 `replacement` (패치 폴더 안 상대 PNG)와 정확한 `sha256`을 함께 선언한다. 크기는 원래 cell_size와 같아야 한다. `anchor:{"from_px":[x,y],"to_px":[x,y]}`는 픽셀 이동이며 불투명 영역이 잘리면 거절한다. 선택한 동작에 효과가 있으면 `event_frames`에 **모든 해당 이벤트의 원래 전체 인덱스 문자열**을 새 프레임 번호 또는 제거용 `null`로 매핑한다. 예를 들어 `{"0":2}`다. no-FX 공격의 접촉 프레임을 삭제·복제하면 새 `contact_frame`을 명시해야 한다.

결과에는 새 scene·portable 요청·원본 입력 사본·`review.json`의 시간/해시/알파 실루엣 차이·동작별 1× GIF/접촉 시트와 실제 다음 명령이 들어간다. `--build`는 같은 프로젝트에 별도 ready B를 만든다. `scene.py build --project <프로젝트> --scene <상대 씬> --source-artifact <그 씬의 실제 Artifact ID> --out <새 상대경로>`로 준비된 씬을 고정하며 A의 요청·실행 파일을 바꾸지 않는다. 미변경 동작은 기존 프레임 바이트와 시간을 보존한다. 알파 하단·바운딩 박스는 실루엣 측정이며 발 접지의 의미 판정이 아니다. GIF는 포즈 미리보기이며 효과 합성이나 플레이 검증을 대신하지 않는다.

### 비교, 근거와 명시적 판정

`review.py compare/check/choose --project "$PROJECT" --record <JSON 파일>`은 구조화된 인자를 읽는다. `resolve --project "$PROJECT"`는 현재 채택 실행과 최신 판정을 읽는다. compare 입력 예시에서 A/B를 실제 같은 프로젝트의 ready run ID로 바꾼다.

```json
{
  "a": "RUN_A", "b": "RUN_B", "review_id": "ab-1",
  "criteria": [
    {"id":"timing","kind":"technical","required":true,"description":"지정한 접촉 프레임과 시간이 보존된다"},
    {"id":"readability","kind":"visual","required":true,"description":"사람이 원속도 공격 실루엣과 접촉을 수용한다"},
    {"id":"first-play","kind":"gameplay","required":true,"description":"명중 전 미완료, 지정 횟수 완료, 빗나감과 재시작이 실제 동작한다"}
  ]
}
```

Comparison은 A/B의 정확한 Run·최신 RunRevision·SceneRevision·RuntimeProduct·모든 연결 산출물의 해시·크기와 실제 필드/동작 시간 diff를 고정한다. 이후 바이트가 바뀌면 새 비교가 필요하다. 시각화의 A/B 화면은 이 고정 기록을 읽는 관찰 도구다.

check 입력은 `review_id`, 새 `check_id`, 비교 대상 `run_id`, 실제 `actor`, `results`를 가진다. 각 결과는 `criterion`, `status:pass|fail|pending`, 구체적인 `reason`, 선택적 프로젝트 상대 `evidence` 파일 목록이다. 시각 `pass`에는 **실제 사용자 발언**에 근거한 `judgement:"human"`과 `attestation:{"source":"user-chat","actor":"<동일 actor>","statement":"<실제 판단 내용>"}`가 필요하다. 사용자가 아직 판단하지 않았다면 pending으로 둔다. 제출 문구 자체는 사람의 신원을 인증하는 장치가 아니므로 에이전트가 승인 발언을 만들어 넣어서는 안 된다.

새 Phaser B를 정상 export 경로로 납품한 뒤 실제 브라우저 근거를 만든다.

```sh
python3 "$STUDIO_ROOT/tools/playcheck.py" run \
  --project "$PROJECT" --export play/실제B출력폴더
```

이 명령은 설정된 로컬 Stagehand MCP로 정상 버튼을 조작한다. 최초 빗나감·방향 반대 빗나감·N-1회 미완료·N회 완료·재시작·접촉 시간을 검사하고 실제 전달된 파일 해시를 기록한다. N=1이면 N-1회 중간 상태 검사는 적용하지 않는다. 프로젝트 `checks/browser-*.json`을 생성하고 `stagehand-browser` 활동을 실제 export receipt와 RuntimeProduct에 연결한다. 설치/브라우저 사전 조건은 [INSTALL](INSTALL.md#070-첫-실행과-재개)에 있다.

gameplay `pass`에는 이 보고서 경로를 `evidence`에 넣는다. 검수기는 정확한 run·runtime SHA·등록된 export 활동·receipt·전체 납품 해시·실제 브라우저 활동의 생성/사용 관계와 관측 검산을 다시 확인한다. `playcheck.py --export ... --run-id ... --observations ... --output ...`의 관측 가져오기는 `observation-import`이며 독립 브라우저 근거로 채택하지 않는다. 그래프 연결과 바이트 고정은 실행 출처의 암호학적 인증이나 사람의 재미·외형 승인이 아니다.

choose 입력은 `review_id`, 새 `decision_id`, `run_id`, 실제 `actor`, `reason`, `outcome`, `expected_decision`이다. 최초 `expected_decision`은 `null`, 이후에는 `resolve`로 읽은 정확한 최신 Decision ID를 넣는다. 오래된 head의 판정은 거절한다.

- `technical-pass`: 필수 technical 기준의 통과만 기록하며 기존 active_run을 유지한다. 제품 채택이 아니다.
- `adopt`: 필수 visual과 gameplay 기준이 모두 있어야 한다. 실제 사용자 시각 승인과 해당 실행의 브라우저 근거를 포함해 모든 필수 기준이 통과해야 active_run을 바꾼다.
- `request-changes`: 수정 사유를 기록하며 기존 active_run을 유지한다.

실패 근거가 있거나 필수 기준이 pending/누락이면 해당 범위의 통과·채택을 막는다. 정정은 새 check에서 같은 비교·후보의 활성 evidence ID를 `supersedes`로 지정하고 `resolution_reason`을 써서 이전 기준 전부를 명시적으로 대체한다. 같은 ID·같은 내용의 재전송은 멱등이며, 다른 내용은 새 ID로 남긴다. 원본 이력은 보존한다.
