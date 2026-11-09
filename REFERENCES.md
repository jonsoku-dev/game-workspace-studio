# 첨부 자료를 제작에 사용하는 색인

새 프로젝트에서는 아래 표에서 현재 입력과 목적에 맞는 항목을 골라 실제 제작·수정·검수에 사용한다. 자료의 이름을 적는 것만으로 적용했다고 기록하지 않는다. 선택한 원본, 가져온 판단, 실행한 도구, 산출물과 실패·수정 근거를 [프로젝트 그래프](GRAPH.md)에 연결한다. 조작과 선택은 채팅이 소유한다.

이 문서는 첨부 원본에서 읽은 사실, 이전에 검토한 외부 자료, 현재 플러그인의 기능을 구분한다. 외부 제품의 기능·수치가 로컬 제작기의 기능이라는 뜻은 아니다. 설치된 `game-studio`, `pixel-asset-pipeline`, `model-assets`는 별개 플러그인이다. 아래 자산 명령을 사용할 때는 해당 설치본의 스킬과 입력 계약을 읽는다. 외부 스킬을 설치하거나 외부 서비스를 자동 호출하라는 지시로 사용하지 않는다.

[설치본 자료 지도](reference-materials.json)에는 아래 원본들의 지문과 해당 설치본에서 대조할 근거가 있다. 여기에 링크된 가이드 PDF·DOCX는 미확보로 남긴다. 새로운 프로젝트의 반영 여부는 그 프로젝트의 지도와 실제 플레이에서 다시 확인한다.

## 원본 식별자

사용자가 제공한 원본은 이미지 16개와 역사적 ZIP 1개다. 식별자는 파일명이 같은 서로 다른 첨부를 구분한다.

| 식별자 | 개별 원본 |
| --- | --- |
| `pixel-formula` | `IMG_6229.png`, 픽셀 제작 공식 |
| `skill-index1` | `4889F87B-18FA-483F-AC4C-030B1AD17A14/1-사진-1.jpg`, awesome 목록 |
| `skill-index2` | 같은 그룹의 `2-사진-2.jpg`, Claude Studios·sprite-gen·Game-Dev 목록 |
| `pixelfx` | `BDCAFFD6-1B0F-470D-B284-DAE98B80E63F/1-사진-1.jpg` |
| `legacy-zip` | `pixel-asset-pipeline-0.1.0.zip`, 초기 정적 제작기 |
| `social1` | `2B62899C-B764-4817-801F-B55EC50B1C67/1-사진-1.jpg`, Polymation 소개 |
| `social2` | 같은 그룹의 `2-사진-2.jpg`, 기존 GIF 편집 |
| `social3` | 같은 그룹의 `3-사진-3.jpg`, Rive·수동 관절 보정 |
| `social4` | 같은 그룹의 `4-사진-4.jpg`, SVG 로고 |
| `feedback` | `D92D6EE4-8BFD-440C-A9C8-3B51360A530C/1-사진-1.jpg`, 전투 반응 |
| `guide-6252` | `IMG_6252.jpeg`, 레벨업 여섯 카드 |
| `guide-6253` | `IMG_6253.jpeg`, 화상 여섯 카드 |
| `guide-6254` | `IMG_6254.jpeg`, 피격 여섯 카드 |
| `guide-6255` | `IMG_6255.jpeg`, Magnet |
| `guide-6256` | `IMG_6256.jpeg`, Pop |
| `guide-6257` | `IMG_6257.jpeg`, Sparkle |
| `guide-6258` | `IMG_6258.jpeg`, Bonus Combo |

## 새 게임에서 고르는 경로

| 지금 필요한 일 | 읽을 항목 | 실제 다음 행동과 완료 근거 |
| --- | --- | --- |
| 게임 아이디어·화풍·첫 장면을 정하기 | 초기 스킬 목록, 픽셀 제작 공식 | `game-studio`의 새 게임 대화에서 핵심 조작·실패·완료와 게임 크기의 대표 그림을 정한다. 열린 선택과 이미 정한 제약을 구분한다. |
| 흐린 픽셀 원화 정리 | 픽셀 제작 공식, 소셜 1 | `pixel-asset snap` 또는 `build --draft` 후 1× 원본·결과를 비교한다. 얼굴·외곽선 손실은 사람이 확인한다. |
| 한 인물의 게임 동작·Rive | 소셜 3, sprite-gen, Agent Sprite Forge | 동작별 완성 PNG를 작화해 `character`·`rive`로 묶는다. 사용자가 컷아웃을 선택했을 때만 `rig-draft`·`motion`을 사용한다. 원속도 실루엣·접지·연결·런타임 상태 전환을 확인한다. |
| 원래 GIF의 마법을 보존하며 수정 | 소셜 2 | `effect-clip`으로 원본 프레임·크기·단계를 고정하고 `action-set`과 호스트 접촉 판정에 연결한다. 접촉 전 무득점과 실제 접촉을 비교한다. |
| 로고·아이콘을 작게 써도 읽기 | 소셜 4 | [SVG 심벌 절차](starter/identity/LOGO.md)로 다른 구조의 후보를 만들고 16·32·128px에서 비교한다. 선택하지 않은 후보로 게임을 교체하지 않는다. |
| 전투·수집·UI·생활 행동의 손맛 | 일반 피드백 1장, 가이드 이미지 7장, pixelfx | [PLAYBOOK](PLAYBOOK.md)에서 이벤트별 조합을 골라 [FEEDBACK](FEEDBACK.md)의 현재 엔진 계약에 연결한다. 정상·거절·빗맞음·복구·무음·움직임 감소를 실제 게임에서 비교한다. |
| 3D 소품과 씬 | 초기 스킬 목록의 3D 관련 자료 | 설치된 `model-assets`로 정적 `.blend`·GLB·예산·로더 결과를 확인하고 스튜디오 씬에 배치한다. 작은 크기의 외관과 실제 엔진 플레이는 별도 검수한다. |
| 기존 게임 수정·버그·다음 판 | 초기 스튜디오 자료, 행동 피드백 원칙 | `game-studio`의 수정 경로에서 기준판을 보존하고 `web_revision.py`로 새 판을 만든다. 버그는 기준판 실패·수정판 통과를 비교한다. 다음 판은 이전 공략이 실패하는 상황과 새 공략 성공을 함께 확인한다. |

## 초기 픽셀 제작 공식

`zero_f_i_l_m`의 `IMG_6229.png` 원본을 직접 읽었다. 출처 대화는 [픽셀아트 테스트 결과](https://chatgpt.com/c/6aefaf49-df00-83ec-87df-786845339c03)다. 이후의 GIF 재편집 화면과는 다른 자료다. 화면의 제안은 자리표와 발선, `STYLE · OUTLINE · VIEW · BACKGROUND`, 명시한 팔레트, 문자·로고·붉은 십자 금지, 생성 후 같은 격자로 정리, 색 고정·외톨이 픽셀 제거·외곽선 재정리, 검사 통과 후 게임 투입이다. 색 수 상한은 캐릭터 16·큰 소품 24·타일 12·아이콘 12로 표시된다. 이미지에 나온 수치는 원 게시물의 제안이지 모든 장르의 보편 기준이 아니다.

| 사용자 의도 | 현재 연결 지점 | 실제 검사와 한계 |
| --- | --- | --- |
| 같은 게임의 그림을 같은 규격으로 만들기 | `pixel-asset-pipeline`의 `build`, `validate`, `compare`, `variant`, `tile`과 공유 profile | `spec.py`의 `art_direction()`이 배치 가이드·스타일·시점·외곽선·팔레트·투명 배경·금지 항목을 전달한다. `raster.validate()`는 실제 크기·RGBA·이진 알파·팔레트 밖 색 0·색 수·외톨이 비율 `< 0.03`·가장자리·캐릭터 발선을 검사한다. `tile`은 별도 반복 지형 계약을 따른다. |
| 생성 뒤 새 게임 크기에서 고치기 | `build --draft` 또는 `snap`의 원본·결과 비교와 새 출력 경로 | “재시도 거의 없음”, 항상 두 번 호출이라는 광고성 결과는 보장하지 않는다. 색 제한을 통과해도 얼굴·실루엣·가독성은 실패할 수 있다. 이미 그린 그림을 무조건 새로 생성하지 않는다. |

파일 지문은 `3f04acc27a3e9d37d3a120f436ddeb0350fd4b87dacad6b802729968a4115768`이다. 원 게시물 영상·시트는 확보하지 않았다.

픽셀아트 테스트 대화의 `dot_pixel_art_test_pack.zip`, `validation_report.json`, `comparison.png`, `sprite_48x48.png`, `pixel-asset-pipeline-skill.zip`, `pixel-asset-pipeline-full.zip` 링크는 대화에서 생성한 출력이다. 사용자 첨부 원본 16개에 더하지 않는다. 이 파일들의 원래 바이트를 확보·검사했다는 뜻도 아니다. 현재 소스에 동등한 기능이 있어도 원 대화 산출물의 바이트나 검증 결과와 같다고 주장하지 않는다.

## 초기 스킬 목록과 이름으로 지정된 자료

초기 Codex 대화 `01a1b937-be1a-7d73-bc78-13c0e33234e5`의 스킬 소개 두 장과 후속 pixelfx 한 장을 복구해 직접 읽었다. 아래 이름별 대응은 원본 화면·작업 공간의 `assets/docs/references.md`, `assets/docs/model-references.md`, `assets/docs/sprite-forge.md`와 현재 로컬 계약을 대조한 것이다. 현재 upstream을 새로 실행·검증한 결과가 아니다.

| 원본 그룹·파일 | 화면에서 확인한 개별 자료와 범위 |
| --- | --- |
| `4889F87B-18FA-483F-AC4C-030B1AD17A14/1-사진-1.jpg` | awesome-gamedev-agent-skills. 엔진·장르·시스템·아트·출시 스킬을 소개하며 엔진은 별도 설치하고 완성 게임을 보장하지 않는다고 설명한다. 실제 게임을 실행하며 고친다는 검수 원칙을 Studio의 첫 플레이·수정 경로에 적용한다. |
| `4889F87B-18FA-483F-AC4C-030B1AD17A14/2-사진-2.jpg` | Claude Code Game Studios, sprite-gen, Game-Dev Agentic Skills 세 항목이 각각 등장한다. 화면은 첫 항목의 README와 실제 실행 문서의 개수 차이를 직접 언급하며, 영상은 sprite-gen README 데모이고 나머지는 README 요약이라고 밝힌다. 소개 문구와 실제 구현·실행을 구분한다. |
| `BDCAFFD6-1B0F-470D-B284-DAE98B80E63F/1-사진-1.jpg` | q_deep_runner의 pixelfx 소개. 244개·21분류·공격 동작 12개·그리기→렌더→보기→수정·시트 내보내기·팔레트 교체를 설명한다. 이 외부 카탈로그를 Pixel의 자체 프리셋 수로 사용하지 않는다. |

`legacy-zip` 원본은 작업 공간의 `assets/dist/pixel-asset-pipeline-0.1.0.zip`에서 확보했다. 크기는 11,832바이트, SHA-256은 `e1f56b1c0bd8f8a07afc2837d90c0e704cd586b51751b870583bd51e11779bbc`다. 압축을 실행하거나 설치하지 않고 `zipfile.read`로 내용을 읽었다. 항목 9개는 marketplace·SKILL·plugin manifest·pyproject·패키지 init·CLI·provider·raster·spec이다. manifest는 0.1.0이며 실제 옛 스킬·코드는 정적 `character/icon/item`의 `build`·`validate`, 공유 profile·팔레트·외곽선·발선, 로컬 초안 또는 명시한 Codex 생성 경로를 담는다.

사용자 의도는 초기 제작기를 현재 플러그인에서 이어 쓰는 것이다. 현재 Pixel의 `build`·`validate`와 요청·검사 계약에서 그 정적 경로를 확인하고, 동작·Rive·효과는 후속 기능으로 구분한다. 이 ZIP에 후속 명령이 있었다고 소급하지 않는다. 현재 제작·수정은 소스와 실제 설치본을 기준으로 하며, 역사적 ZIP을 덮어쓰거나 최신 설치본으로 실행하지 않았다.

| 이름별 원본 | 사용자가 가져오려는 방법 | 설치본에서 사용할 지점 | 실제 확인·실패와 범위 |
| --- | --- | --- | --- |
| [awesome-gamedev-agent-skills / create-game-assets](https://github.com/gamedev-skills/awesome-gamedev-agent-skills) | 게임 카메라·표시 크기·공유 미술 기준부터 정하고 대표 자산을 검수한 뒤 세트 제작 | Studio의 재미·아트 대화, Pixel의 profile·`compare`·`validate`, Model의 다각도·작은 크기 검수 | 기존 woodland 세트·타일 반복·등불 검토 근거가 있다. 인벤토리·세이브·던전·출시는 이 자료 이름만으로 자동 지원되지 않는다. 새 게임에서는 대표 자산 하나를 실제 배경에 놓고 읽히는지 먼저 확인한다. |
| [Claude Code Game Studios / technical-artist](https://github.com/Donchitos/Claude-Code-Game-Studios) | 기획·제작·감사를 분리하고 게임의 실제 작업 경로를 유지 | Studio가 목표·씬·검수를, Pixel·Model이 제작과 측정값을 소유. `start.py`, `scene.py`, `review.py`와 그래프에서 결과를 연결 | 역할 설명을 로컬 조직도나 에이전트 묶음으로 복제하지 않았다. 기술 통과와 사람의 채택을 분리한다. Blender 모델 생성 구현이 이 외부 저장소에 있다는 근거로 쓰지 않는다. |
| [sprite-gen](https://github.com/aldegad/sprite-gen) | 기준 인물·팔레트·동작·시트·루프를 유지하며 수정 | Pixel의 `sheet`·`action-set`·`motion`·`character`·`rive`·`variant`. 새 포즈는 실제로 작화하고 기존 픽셀은 선언된 범위만 재사용 | Scout Actions의 프레임 복원 검사와 Rive 원속도 검토 기록을 참고한다. 스크린샷만으로 자동 액션 생성이나 영상 보간 기능을 보장하지 않는다. 2D `scene/model.py`를 3D 메시 제작기로 분류하지 않는다. |
| [Game-Dev-Agentic-Skills](https://github.com/thedivergentai/Game-Dev-Agentic-Skills) | 대상 엔진에 맞는 기능·재질·조명·월드 구현을 고르기 | Studio의 엔진별 exporter·검수 문서, Model의 정적 GLB 제작 계약 | Godot·Three·Phaser·Unity 경로의 존재는 이 로컬 플러그인 구현에서 확인한다. 외부 Godot·Bevy 스크립트를 포함했다는 뜻이 아니다. Bevy 지원을 주장하지 않으며 Unity Editor 실플레이는 해당 증거가 있어야 한다. |
| [patch-gg/pixelfx](https://github.com/patch-gg/pixelfx) | 팔레트·시드·피벗·시간·앞뒤 레이어와 acting을 분리한 로컬 효과 제작 | Pixel의 자체 `effect`, 로컬 pixelfx 시트·JSON·LICENSE·NOTICE를 받는 `action-set`, Studio의 접촉 판정·피드백 | 기존 검토가 보고한 244개·21분류는 외부 카탈로그 수치다. 로컬 `effect`가 전체 카탈로그를 내장한다는 뜻이 아니다. 실제 가져온 시트의 출처·고지를 유지하고 1×·원속도·접촉 프레임을 검사한다. 픽셀 출력용 IK를 GLB 리그 납품으로 해석하지 않는다. |
| [Agent Sprite Forge](https://github.com/0x0funky/agent-sprite-forge) | 승인 마스터를 유지하며 여섯 동작을 만들고 로컬에서 정합·루프·타이밍·크레딧 검사 | Pixel `action-set`은 이미 준비된 여섯 동작 PNG와 효과를 받는다. `character`·`rive`는 작화된 상태별 포즈를 선택해 납품 | 기존 조사 `sprite-forge.md`와 Scout Actions의 입력·아틀라스 복원 근거가 있다. ASF 영상 생성 API·코드·쇼케이스를 설치본에 넣거나 호출한 것은 아니다. 준비한 프레임의 포장과 원화에서 새로운 동작을 그리는 일을 구분한다. |

초기 목록에서 제안한 3D 제작 방식은 정적 `model-assets`에 적용한다. 실제 `.blend`·raw GLB·컴파일 GLB·영수증·로더 검사를 구분하고, 숨은 면·재질·비율은 제작자의 결정으로 기록한다. 기술 검사를 통과한 첫 등불도 브라우저에서 내부 광원이 가려지는 외관 문제가 있었으므로 모델 형태·유리·조명을 다시 검토했다. 이 사례는 외부 자료의 코드가 아니라 검수 방법을 적용한 결과다. 상세한 과거 근거는 `assets/docs/model-quality.md`에 있다.

## 소셜 화면 네 장

원본 그룹은 `2B62899C-B764-4817-801F-B55EC50B1C67`이며 네 JPEG를 모두 직접 읽었다. 원본 릴스 전체·제작 입력·정확한 게시물 URL은 확보하지 않았다. 과거의 공개 문서 대조와 실행 근거는 작업 공간의 `release/REFERENCE-WORKFLOWS.md`에 있다.

| 원본 항목 | 사용자 의도와 원본에서 읽은 사실 | 설치본의 구체적 행동 | 검사·실패·범위 |
| --- | --- | --- | --- |
| `1-사진-1.jpg`, Polymation 소개 | 흐린 AI 픽셀 원화를 실제 격자로 정리하고 이후 제작에 쓰기. 화면에는 제품 주소·무료 export 안내·MCP 클라이언트 지원 문구가 있음 | `pixel-asset snap`으로 크롭·목표 격자·팔레트를 명시하고 1× 원본·결과·지문 비교 | 자체 시험 PNG의 3,579색→16색 결과는 로컬 예제의 측정이며 원 게시물의 결과가 아니다. Polymation 서비스·무료 횟수·내부 알고리즘은 설치본 기능이 아니다. |
| `2-사진-2.jpg`, zero_f_i_l_m의 기존 GIF | 새로 그리지 않고 배경 제거·캐릭터 크기 축소·모으기→비행→명중으로 재편집 | `pixel-asset effect-clip`에 사용 가능한 GIF·고지·단계별 원본 프레임·시간·피벗을 넣고 `action-set`과 호스트 판정에 연결 | GIF 표시 프레임 복원, 단색 가장자리 배경 제거, 내부 같은 색 보존을 확인한다. 복잡한 배경 분리는 지원하지 않는다. 원 게시자의 GIF는 없으며 moonshot-fx는 명시한 자체 시험 GIF다. 접촉 전 무득점·범위 밖·등진 공격·완료·재시작 근거가 있다. |
| `3-사진-3.jpg`, Polymation의 Rive | 원화 정리·관절 수동 보정·동작 선택이 가능한 단일 파일. 게시자는 22,682→36색·17본·관절 2곳 수정·164KB를 보고 | 컷아웃 선택 시 `rig-draft`→편집한 마스크·관절→`motion`. 상태별 작화는 `character`의 `frames`→`rive`→실제 공식 런타임 재생 | 로컬 리그 초안은 여섯 부위이며 17본 자동 재현이 아니다. 관절 이동 전후 접점 오차 0.635→0.334px 기록이 있다. Rive 초기 공격·인사에서 팔다리 분리 실패를 발견해 수정했다. 원 게시자의 PNG·.riv는 없으며 live puppet 본 편집을 납품한다고 주장하지 않는다. |
| `4-사진-4.jpg`, logo-design 소개 | 편집 가능한 SVG, 여러 시안, 작은 프로필 크기에서 검수 | [로고 절차](starter/identity/LOGO.md)의 브리프→구조 다른 세 후보→정적 SVG 검사→밝고 어두운 16·32·128px 비교→채택 기록 | 기존 A·B·C 후보에서 외부 링크처럼 읽히는 B와 의미가 약한 C를 구분했다. 후보 생성은 자동 채택이 아니다. 외부 로고 라이브러리·브랜드·폰트는 복사하지 않았다. 화면 단서와 맞는 Kaan Kızıltuğ의 스킬을 과거 대조했지만 게시자·별 수의 동일성은 확정하지 않았다. |

소셜 원본의 SHA-256은 다음과 같다. 같은 이름의 다른 첨부와 혼동하지 않는다.

| 파일 | SHA-256 |
| --- | --- |
| `1-사진-1.jpg` | `2301b1a41169a8af49bdaa470dfe1a3c11c2135af0ce7b0c1d2af602dffd75c5` |
| `2-사진-2.jpg` | `93ea496a755eb9af8d7cdbe2201076afd8bcc8ea18dc03e5b289c5d81ff698ea` |
| `3-사진-3.jpg` | `c3e52d345bcd1d8d33ea87d3a23ca77c98fbd808c3cee971b0a7892196c7b14a` |
| `4-사진-4.jpg` | `bc31875a4aea7338b26b1159a19c09ef43504ba03ff3fc16283bdf681bf278cc` |

## 일반 피드백 화면 한 장

원본은 그룹 `D92D6EE4-8BFD-440C-A9C8-3B51360A530C`의 `1-사진-1.jpg`다. SHA-256은 `eb9e06ba1a80cb6f10a92cc0ac1c2d41d19c6def4fdd9f618a01efab0cd9c5b6`이다. 직접 읽은 @porsukgames 화면은 명중 흰색 강조·눌림, 넉백·3–5프레임 타격 정지, 저음과 연속 타격의 피치 변화, 방향성 베기·불티, 피해 숫자와 지연 체력 표시, 보너스 치명타·마무리 3D 파편을 제안한다. 정지 화면이므로 실제 애니메이션·소리는 확인하지 않았다.

사용자 의도는 게임의 실제 조작에 읽히는 반응을 주는 것이다. [FEEDBACK](FEEDBACK.md)은 이를 이동·UI·수집·상호작용·퍼즐·진행·실패까지 확장한다. Pixel의 `step`·`land`·`pickup`·`slash`·`impact`·`confirm`·`deny`를 필요한 이벤트에만 연결한다. 웹 소리는 `engines/web/feedback.mjs`, Phaser 시트 연결은 씬의 `feedback.effects` 계약을 따른다. 3D는 해당 엔진의 실제 메시·재질·조명 경로를 사용하며 2D 시트를 3D 파편이라고 부르지 않는다.

확인은 실제 접촉·거절·연속 타격·손맛 토글·무음·움직임 감소에서 한다. 명중하지 않은 입력에 피해 숫자·성공음이 생기면 실패다. 이미지의 3–5프레임을 보편 시간으로 고정하지 않는다. 기존 배달 예제는 실제 체력 30→20→5→0과 완료·재시작을 관찰했지만, 영상에 오디오가 있다는 사실은 청취 수락이나 기기 지연 측정이 아니다. 과거 증거는 `release/evidence/game-feel/acceptance.json`과 `examples/courier-feedback/evidence/`에 있다.

## 가이드북 대화와 이미지 일곱 장

[지정 대화](https://chatgpt.com/c/6af112c6-8390-83ee-9c6e-99842bdffa9e)의 본문 1턴과 JPEG 7장을 직접 확인했다. 다시 조회해도 첨부 목록은 JPEG 7장이었으며 `Game_Feel_Playbook_KR.pdf`와 `Game_Feel_Playbook_KR.docx` 본문은 확보하지 못했다. 대화가 보고한 39페이지·280기법·20분류·20레시피를 전체 전사·구현·검증했다고 주장하지 않는다. 실제 전사 범위와 수치·가림 한계는 [PLAYBOOK](PLAYBOOK.md)에 있다.

| 원본 파일 | 구분되는 입력 | 설치본에서 선택·적용할 행동과 검사 |
| --- | --- | --- |
| `IMG_6255.jpeg` | 코인 Step 1 Magnet | 획득 범위·흡인 표시와 실제 수량 확정을 구분한다. 장애물·이미 획득·범위 밖을 검사한다. |
| `IMG_6256.jpeg` | 코인 Step 2 Pop, Scale | 획득 순간 표시용 확대·복귀를 선택한다. 충돌 크기와 실제 수량이 변하지 않는지 검사한다. |
| `IMG_6257.jpeg` | 코인 Step 4 Sparkle | 실제 획득점의 별 장식·수명·겹침을 정한다. Step 3는 첨부에 없으므로 채우지 않는다. |
| `IMG_6258.jpeg` | 코인 Bonus Combo | 실제 시간 조건·배율을 규칙으로 정한 뒤 HUD·음향을 연결한다. 첨부에는 시간창·공식이 없다. |
| `IMG_6253.jpeg` | Burning 여섯 카드 | 불꽃·색·불씨·그을음·고리·피해 tick 중 선택한다. 상태 유지와 실제 피해를 구분하고 해제·중복을 검사한다. |
| `IMG_6254.jpeg` | Taking Damage 여섯 카드 | 넉백·무적 표시·가장자리·하트·색·색 분리 중 선택한다. 체력·방향을 별도 표시하고 점멸 대체·무음·연출 끄기를 검사한다. |
| `IMG_6252.jpeg` | Level Up 여섯 카드 | 빛기둥·배너·나선·바·능력치·고리 도약 중 선택한다. 실제 레벨·능력치를 먼저 확정하고 바 초과·도약은 표시용인지 구분한다. |

각 항목은 PLAYBOOK의 이벤트→층 선택→시작·유지·복구→튜닝→접근성→검수 절차로 이어진다. 예제의 방패 막힘과 측면 명중, 봉화 높이·순서·맥동, 친구 구조와 솔기 수선, 같은 발사의 두 고리 접촉 레시피는 현재 게임 규칙을 적용한 자체 설계다. 다른 장르도 그 게임의 실제 상태 경계에 연결하며 새 필드나 22개 자동 프리셋이 있다고 가정하지 않는다.

작업 공간의 `release/evidence/genre-campaign/guide-source.json`은 일곱 파일의 전체 SHA-256·바이트 수와 미확보 문서를 기록한다. 파일별 수치는 원본 텍스트의 전사이며 영상 측정값이 아니다.

## 설치 기능과 과거 증거를 구분한다

Studio 설치본의 자체 문서는 [README](README.md), [GRAPH](GRAPH.md), [FEEDBACK](FEEDBACK.md), [PLAYBOOK](PLAYBOOK.md), [심벌 절차](starter/identity/LOGO.md)다. Pixel·Model의 스킬·코드는 각자 설치본에서 찾는다. 위 명령은 현재 저장소의 CLI·스킬과 대조했으며 특정 사용자의 활성 설치 버전까지 이 문서로 보장하지 않는다. 실행 전에 실제 설치 루트와 버전을 확인한다.

`assets/docs/`·`release/evidence/`·`examples/`·`PROGRESS.md`는 이 문서를 작성할 때 읽은 작업 공간의 과거 검토·실행 증거다. 설치본에 그 폴더가 전부 들어 있다고 가정하지 않는다. 이 문서의 소스 색인은 원장이나 새 실행 증거를 대신하지 않는다. 새 프로젝트에서는 실제 입력과 검사를 그 프로젝트 그래프에 남긴다.

외부 저장소·브랜드·스크린샷·모델의 권리는 각각 구분한다. 이전 라이선스 조사는 `assets/docs/license-review.md`와 `model-references.md`에 있으며 현재 upstream의 법적 상태를 새로 확인한 결과가 아니다. 실제 코드를 가져오면 선택한 커밋·파일·LICENSE·NOTICE를 확인한다. 특히 pixelfx 입력 시트의 고지와 공식 Rive 런타임의 배포 고지는 결과와 함께 유지한다. 원본 화면을 참고했다고 그 화면의 캐릭터·음원·로고를 납품물에 복제하지 않는다.
