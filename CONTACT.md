# 도구와 표면의 접촉에서 효과 만들기

전투 애니메이션이 정확히 끝나도 총구가 몸통에서 발사되거나, 깎은 철판이 멀쩡하면 효과가 별도 그림처럼 읽힌다. 실제 플레이에서 손·도구·상대 표면·남은 흔적을 한 장면으로 본다.

## 독립 웹게임에서 쓰기

`genre.json`에 `"contact":true`를 넣은 뒤 일반 `tools/web_game.py --project PROJECT --out play/first`로 내보낸다. 설치본의 `contact.mjs`가 결과 폴더에 복사되고 해시가 영수증에 기록된다. 프로젝트 소스에 동명의 파일을 넣지 않는다.

```js
import {createContactTracker} from './contact.mjs';
const pairs = createContactTracker();
// tool.x/y/radius와 surface.a/b는 바로 그 화면에 그릴 월드 좌표다.
const contact = pairs.update('wheel','panel',tool,surface);
if (contact.phase === 'enter' || contact.phase === 'stay') {
  // contact.point에서 시작하고 normal/slip/material로 방향·양·반응을 정한다.
  // 게임 규칙이 허용할 때만 절삭량과 표면 손상을 갱신한다.
}
```

원형 날과 유한 선분의 양 끝까지 판정한다. `surface.velocity`는 표면의 이동 속도, `tool.angularVelocity`는 화면 좌표(y가 아래)에서 시계방향인 rad/s다. 미끄럼 속도는 공구 자체의 회전도 포함한다. 떨어진 쌍에도 update를 계속 호출해야 `exit`가 생긴다. 화면 전환·재도전에서는 상태를 초기화한다. 이산 샘플 사이를 순간이동하는 고속 탄환의 연속 충돌은 이 도구의 범위 밖이다.

## 작화에 붙이는 효과

발 피벗과 현재 노출로 무기를 그린 다음 별도 몸통 오프셋으로 효과를 계산하지 않는다. 프레임별 sockets에 실제 손잡이·칼끝·총구를 표시한다. `combat_motion.py` 입력의 sockets 좌표는 해당 crop 안의 원본 픽셀이다. 컴파일 때 크기 변경·붙여넣기를 발 피벗과 동일하게 적용한다. sampler에서 그린 프레임의 좌표·방향·배율로 월드 위치를 얻는다. 소켓이 없는 자세에서 임의의 몸통 위치를 소켓으로 쓰지 않는다.

날 잔상은 현재 손잡이와 칼끝 두 점을 `createTrailHistory`에 넣고 인접 시간 샘플끼리만 잇는다. `breakBefore`가 참인 구간은 잇지 않는다. 발사 순간까지 붙어 있던 광원은 발사체가 떨어지는 순간에 독립 월드 좌표로 전환한다. 순간이동·방향 전환·클립 교체에서는 필요한 경우 reset한다.

## 시각 검토

1. 효과를 줄인 장면에서도 도구와 피격 대상의 힘·이동 방향이 보이는지 확인한다.
2. 원점 고정 방식과 실제 접촉 방식에 동일 입력을 재생한다. 원점 외에는 입자·색·카메라·게임 상태를 고정한다.
3. 헛돌 때 파편이 없어야 한다. 실제 접촉점이 움직이면 새 파편은 따라가고, 이미 나온 파편은 월드에 남는다. 금속·보호막·코어는 서로 다른 표면 반응을 보인다.
4. 한 번의 파괴에서 밝은 중심 하나에 집중한다. 이후에는 표면 변형·분리된 파편이 결과를 전달한다. 원속도 검토와 제작자/플레이어의 취향 판단을 수치 검사와 구분한다.

제작 근거: Epic의 [Paper 2D sprite sockets](https://dev.epicgames.com/documentation/unreal-engine/paper-2d-sprite-sockets-in-unreal-engine) 및 [animation notifies/trails](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-notifies-in-unreal-engine), Guillermo Rossell의 [trail/impact 제작 사례](https://80.lv/articles/trail-impact-vfx-production), Greg Hird-Rutter의 [표면별 충돌 제작 사례](https://80.lv/articles/006sdf-008cgs-learning-more-about-vfx-production-for-films-games). 여기서 Studio의 2D 좌표·절삭 규칙은 이 사례들을 바탕으로 만든 자체 구현이다.
