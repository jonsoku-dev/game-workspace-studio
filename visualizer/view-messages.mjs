import { t } from './i18n.mjs';

const messages = {
  fallback: ['미리보기를 표시할 수 없어요. 아래 원문 오류를 확인해 주세요.', 'プレビューを表示できません。以下の元のエラーを確認してください。'],
  keyboard: ['장면 살펴보기. Space: 일시정지·재생, 좌우 방향키: 회전, 위아래 방향키: 확대·축소, Home: 시점 초기화, 대괄호: 시간 이동.', 'シーンの確認。Space：一時停止・再生、左右キー：回転、上下キー：拡大・縮小、Home：視点をリセット、角括弧：時間を移動。'],
  runtime: ['표시 가능한 준비 완료 장면이 아니거나 좌표 설정이 올바르지 않아요.', '表示可能な準備完了のシーンではないか、座標設定が正しくありません。'],
  transform: ['장면 노드의 변환 값이나 식별자가 올바르지 않아요.', 'シーンノードの変換値または識別子が正しくありません。'],
  cycle: ['장면 노드의 부모 관계가 순환해요.', 'シーンノードの親子関係が循環しています。'],
  parent: ['장면 노드가 참조하는 부모가 없어요.', 'シーンノードが参照する親がありません。'],
  duplicate: ['장면에 중복된 에셋 식별자가 있어요.', 'シーン内に重複したアセット識別子があります。'],
  missing: ['장면 노드가 참조하는 에셋이 없어요.', 'シーンノードが参照するアセットがありません。'],
  producer: ['이 장면의 제작기는 미리보기에서 지원하지 않아요.', 'このシーンの制作ツールはプレビューに対応していません。'],
  effect: ['3D 입자 효과의 설정이 올바르지 않아요.', '3Dパーティクル効果の設定が正しくありません。'],
  frames: ['스프라이트 프레임의 영역이나 재생 시간이 올바르지 않아요.', 'スプライトフレームの領域または再生時間が正しくありません。'],
  actions: ['캐릭터 동작 메타데이터가 올바르지 않아요.', 'キャラクター動作のメタデータが正しくありません。'],
  contact: ['동작의 접촉 효과 정보가 올바르지 않아요.', '動作の接触エフェクト情報が正しくありません。'],
  native: ['접촉 효과가 원본 아틀라스 메타데이터와 일치하지 않아요.', '接触エフェクトが元のアトラスメタデータと一致しません。'],
  sourceMesh: ['3D 효과에 표시할 원본 메시가 없어요.', '3Dエフェクトに表示する元のメッシュがありません。'],
  size: ['장면의 표시 크기(size_m)는 0보다 커야 해요.', 'シーンの表示サイズ（size_m）は0より大きい必要があります。'],
  action: ['지정된 스프라이트 동작이 없어요.', '指定されたスプライト動作がありません。'],
  bounds: ['장면에 표시 가능한 유효한 메시 영역이 없어요.', 'シーンに表示可能な有効なメッシュ範囲がありません。'],
  load: ['장면 에셋 파일을 불러오지 못했어요.', 'シーンのアセットファイルを読み込めませんでした。'],
  receipt: ['GLB 파일과 일치하는 성공한 제작 영수증을 확인할 수 없어요.', 'GLBファイルと一致する成功した制作レシートを確認できません。'],
  glb: ['GLB 파일 형식이 올바르지 않거나 내용이 잘렸어요.', 'GLBファイルの形式が正しくないか、内容が途切れています。'],
  scene: ['GLB 파일에 기본 장면이 지정되어 있지 않아요.', 'GLBファイルにデフォルトシーンが指定されていません。'],
  external: ['외부 리소스는 불러올 수 없어요. 리소스를 GLB 파일 안에 포함해 주세요.', '外部リソースは読み込めません。リソースをGLBファイル内に含めてください。'],
  decoder: ['Draco·KTX2 외부 디코더는 지원하지 않아요.', 'Draco・KTX2の外部デコーダーには対応していません。'],
  textureFormat: ['GLB 안에 포함된 PNG·JPEG 텍스처만 지원해요.', 'GLB内に含まれるPNG・JPEGテクスチャのみに対応しています。'],
  nodeTexture: ['이 검사는 텍스처 없는 GLB만 지원해요. 포함된 텍스처는 브라우저에서 확인해 주세요.', 'この検査はテクスチャなしのGLBのみに対応しています。埋め込みテクスチャはブラウザーで確認してください。'],
  static: ['정적인 삼각형 메시만 지원해요. 애니메이션·스킨·모프는 표시할 수 없어요.', '静的な三角形メッシュのみに対応しています。アニメーション・スキン・モーフは表示できません。'],
  geometry: ['메시의 정점·인덱스·삼각형 데이터가 올바르지 않아요.', 'メッシュの頂点・インデックス・三角形データが正しくありません。'],
  invisible: ['메시가 보이지 않아 표시 가능한 모델로 확인할 수 없어요.', 'メッシュが非表示のため、表示可能なモデルとして確認できません。'],
  uv: ['텍스처의 UV 좌표가 없거나 올바르지 않아요.', 'テクスチャのUV座標がないか、正しくありません。'],
  texture: ['모델의 텍스처를 정상적으로 디코딩하지 못했어요.', 'モデルのテクスチャを正常にデコードできませんでした。'],
  color: ['기본 색상 텍스처가 sRGB 형식이 아니에요.', 'ベースカラーテクスチャがsRGB形式ではありません。'],
  webgl: ['WebGL을 시작할 수 없어 미리보기를 표시하지 못했어요.', 'WebGLを開始できないため、プレビューを表示できませんでした。']
};

const known = new Map([
  ['Expected ready scene runtime with meters, right-handed +Y coordinates', 'runtime'],
  ['Invalid or duplicate scene node transform', 'transform'], ['Scene node parent cycle', 'cycle'],
  ['Scene node parent missing', 'parent'], ['Duplicate scene asset', 'duplicate'],
  ['Node references missing asset', 'missing'], ['Unsupported scene producer', 'producer'],
  ['Invalid mesh-particles effect descriptor', 'effect'], ['Invalid action atlas frames', 'frames'],
  ['Invalid sprite frame metadata', 'frames'], ['Invalid action-set metadata', 'actions'],
  ['Invalid action contact event', 'contact'], ['Contact effect differs from native pixelfx atlas metadata', 'native'],
  ['Mesh effect has no source mesh', 'sourceMesh'], ['Action size_m must be positive', 'size'],
  ['Effect size_m must be positive', 'size'], ['Unknown named sprite action', 'action'],
  ['Scene has no drawable bounds', 'bounds'],
  ['Expected successful webstage-asset/1.0 gltf receipt matching GLB byte length', 'receipt'],
  ['Expected GLB version 2', 'glb'], ['Truncated GLB JSON', 'glb'],
  ['Expected an explicit default scene', 'scene'], ['GLB has no default scene', 'scene'],
  ['External or URI resources are forbidden; embed all resources in GLB', 'external'],
  ['Network and external resources are forbidden', 'external'],
  ['Draco and KTX2 require unsupported external decoders', 'decoder'],
  ['Only embedded PNG/JPEG textures are supported', 'textureFormat'],
  ['Node inspection supports untextured GLBs only; use browser verification for embedded PNG/JPEG', 'nodeTexture'],
  ...['Only static meshes are supported', 'Only static triangle primitives are supported', 'Only triangle meshes are supported', 'Skinned meshes are outside the static model scope'].map(message => [message, 'static']),
  ...['Mesh has no vertices', 'Nonfinite mesh vertex', 'Mesh index is outside vertex range', 'Expected nonempty triangle mesh'].map(message => [message, 'geometry']),
  ['Invisible mesh cannot establish drawable acceptance', 'invisible'],
  ['Textured mesh is missing matching UV coordinates', 'uv'], ['Nonfinite UV coordinate', 'uv'],
  ['Texture image did not decode', 'texture'], ['GLTFLoader failed to decode all base color textures', 'texture'],
  ['Base color texture is not sRGB', 'color'], ['Expected nonempty finite drawable mesh bounds', 'bounds'],
  ['Error creating WebGL context.', 'webgl']
]);

export const inspectionLabel = () => t(messages, 'keyboard');

// Keep original diagnostics intact; this text is only for the visualizer's feedback.
export function renderErrorText(error) {
  const detail = String(error?.message ?? error ?? '');
  const key = known.get(detail) ?? (/^Unable to load scene asset \(\d+\)$/.test(detail) ? 'load' : 'fallback');
  return `${t(messages, key)}${detail ? `\n${detail}` : ''}`;
}
