# Game Studio

게임 기획·씬·플레이 시스템·엔진 임포트를 관리하는 별도 프로젝트다. 아트 제작은 설치된 에셋 제작기를 호출한다. 스튜디오는 요청, 게임에 채택한 산출물과 엔진 내 배치를 소유한다.

## 설치된 2D 제작기 사용

[보상 효과 요청](assets/requests/reward.json)을 이 폴더에서 설치된 `pixel-asset` 0.2.1로 실행했다. 결과의 `files`에서 [투명 시트](assets/generated/reward/sheet.png)와 [프레임·시간·피벗](assets/generated/reward/sheet.json)을 읽는다. [재생 미리보기](assets/generated/reward/preview.gif)

```sh
pixel-asset effect --request assets/requests/reward.json --out assets/generated/reward-v2
```

출력 경로는 새 폴더여야 한다. 실제 검증에서는 네트워크를 차단한 상태에서 32×32 효과 10프레임을 생성하고 시트의 프레임 사각형과 종료 프레임을 확인했다.

## 제안된 3D 경계

에셋 저장소의 별도 3D 제작기가 편집 원본·GLB·미리보기·단위와 축 등의 메타데이터를 담당한다. 스튜디오는 납품된 GLB를 선택한 엔진의 자산으로 등록하고 실제 배치·재생을 확인한다. 현재 설치·검증된 제작기는 2D이며 3D 인터페이스는 설계 후보이다.
