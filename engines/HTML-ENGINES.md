# 웹 게임 엔진 선택과 검증 범위

Game Studio는 고정된 씬·에셋을 로컬 게임 엔진에 전달한다. 검수 화면, 실제 웹 게임, Godot 게임, Unity 에디터 프로젝트는 서로 다른 실행 결과다. 제작 데이터나 인증 정보를 업체 서버에 전송하는 경로는 사용하지 않는다.

| 런타임 | 적합한 역할 | 이 릴리스의 선택 | 공식 근거 |
| --- | --- | --- | --- |
| Three.js | 3D 렌더링 라이브러리. GLTFLoader로 GLB를 읽고, InstancedMesh로 각각 다른 위치의 불티 메시를 그릴 수 있다. 게임 규칙과 입력 처리는 호스트가 구현한다. | r187을 고정해 3D 웹 게임과 검수 화면에 사용한다. MIT. | [로더](https://threejs.org/docs/pages/GLTFLoader.html) · [인스턴싱](https://threejs.org/docs/pages/InstancedMesh.html) · [소스와 라이선스](https://github.com/mrdoob/three.js) |
| Phaser | 씬·입력·애니메이션·카메라·물리를 제공하는 2D HTML5 게임 프레임워크. 아틀라스 프레임과 애니메이션을 실게임에 연결하기 좋다. | 통합 버전은 3.90.0. 4.x도 배포되고 있으며 4.x 호환을 이 버전의 검사 결과에서 추정하지 않는다. 자체 호스팅, MIT. | [3.90 릴리스](https://phaser.io/download/release/v3.90.0) · [애니메이션](https://docs.phaser.io/phaser/concepts/animations) · [4.2.1 소스](https://github.com/phaserjs/phaser/tree/v4.2.1) |
| Babylon.js | 3D 엔진. glTF 로더, SceneLoader 및 엔진 수준의 카메라와 씬 관리가 필요한 프로젝트에 적합하다. 로더와 필요한 디코더도 로컬에 둘 수 있다. | 별도 엔진 후보. 현재 Three 어댑터에서 Babylon 실측을 주장하지 않는다. Apache-2.0. | [공식 저장소](https://github.com/BabylonJS/Babylon.js) · [로더](https://doc.babylonjs.com/features/featuresDeepDive/importers/loadingFileTypes/) |
| PlayCanvas Engine | 3D ECS 엔진. 독립 Engine은 클라우드 Editor 없이 실행되며 glTF/GLB 컨테이너를 인스턴스화한다. | 협업형 웹 3D·ECS가 필요할 때의 후보. 온라인 Editor/API를 채택하지 않아도 된다. Engine은 MIT. | [독립 실행](https://developer.playcanvas.com/user-manual/engine/standalone/) · [형식](https://developer.playcanvas.com/user-manual/assets/supported-formats/) · [소스](https://github.com/playcanvas/engine) |
| PixiJS | 2D 렌더링 엔진. 스프라이트시트와 AnimatedSprite에 강하다. 게임 씬·판정·상태는 별도로 조립한다. | 커스텀 2D 렌더링용 후보. 현재 Phaser와 중복 도입하지 않았다. MIT. | [PixiJS 개요](https://pixijs.com/8.x/guides/getting-started/intro) · [소스](https://github.com/pixijs/pixijs) |
| Excalibur | TypeScript 기반 2D 게임 엔진. ECS·물리·입력·프레임 애니메이션을 함께 제공한다. | Phaser 이외의 코드 중심 2D 후보. BSD-2-Clause. | [공식 문서](https://excaliburjs.com/docs/) · [애니메이션](https://excaliburjs.com/docs/animation/) · [소스](https://github.com/excaliburjs/Excalibur) |
| GDevelop | 이벤트와 편집기를 중심으로 2D·3D 게임을 제작하고 정적 HTML5 게임으로 내보낼 수 있다. | 노코드 저작자가 주 사용자가 될 때 재검토한다. 오픈소스 Core/GDJS는 MIT이며 온라인 배포 서비스는 사용하지 않는다. | [소스·라이선스](https://github.com/4ian/GDevelop) · [로컬 HTML5 내보내기](https://wiki.gdevelop.io/gdevelop5/publishing/html5_game_in_a_local_folder/) |
| Cocos Creator | 에디터에서 웹 데스크톱·모바일 타깃으로 빌드하는 2D/3D 엔진. 기존 코드 기반 Studio와 연결하려면 Cocos 프로젝트/컴포넌트 단계가 추가된다. | 모바일 웹 제작 조직의 후보. cocos-engine 3.8.7 코드는 MIT이고 별도 에디터·서비스 조건은 구분한다. | [웹 배포](https://docs.cocos.com/creator/3.8/manual/en/editor/publish/publish-web.html) · [엔진 고지](https://github.com/cocos/cocos-engine/blob/v3.8.7/LICENSE.md) |
| Defold | 게임 프로젝트를 HTML5 번들로 내보낸다. 웹 런타임과 네이티브 타깃을 같은 저작 체계로 운영하려는 팀의 후보다. | 별도 프로젝트·툴체인이 필요하다. 엔진 재배포를 검토할 때 Defold 전용 라이선스를 확인한다. | [HTML5 번들](https://defold.com/manuals/html5/) · [라이선스](https://defold.com/license/) |

라이브러리·에셋·디코더는 각각 해당 버전의 고지를 유지한다. 위 후보들의 설명은 공식 문서 조사다. Studio가 실제로 내보내고 실행한 타깃과 검증 환경은 [Godot 인수 기록](godot/README.md), [웹 3D 기록](web/README.md), [Phaser 기록](web/phaser/README.md), [Unity 범위](unity/README.md)을 따른다.
