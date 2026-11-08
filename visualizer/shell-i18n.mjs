import { getLocale, setLocale, t } from './i18n.mjs';

const copy = {
  title: ['Game Studio · 장면 검사', 'Game Studio · シーン検査'],
  skip: ['장면으로 건너뛰기', 'シーンへスキップ'],
  identity: ['Game Studio 작업실', 'Game Studio ワークスペース'],
  projectPicker: ['관찰할 프로젝트', '観察するプロジェクト'],
  readonly: ['읽기 전용', '読み取り専用'],
  history: ['실행 이력', '実行履歴'],
  projects: ['프로젝트', 'プロジェクト'],
  overviewHelp: ['Codex 채팅에서 제작을 지시하고, 여기서 결과를 확인하세요.', 'Codex のチャットで制作を依頼し、この画面で結果を確認できます。'],
  historyRecords: ['실행 기록', '実行記録'],
  viewTools: ['보기 도구', '表示ツール'],
  productionDetails: ['기획 · 제작 과정', '企画 · 制作工程'],
  graphDetails: ['항목 · 근거 살펴보기', '項目・根拠を調べる'],
  activities: ['독립 작업 · 검증', '独立作業 · 検証'],
  views: ['작업 보기', '作業ビュー'],
  sceneAssets: ['장면 · 에셋', 'シーン · アセット'],
  causalGraph: ['인과 그래프', '因果グラフ'],
  actionPreview: ['동작 미리보기', '動作プレビュー'],
  actionPreviewReadonly: ['읽기 전용 동작 미리보기', '読み取り専用の動作プレビュー'],
  recordedAction: ['기록된 동작', '記録された動作'],
  stepFrame: ['100밀리초 뒤 프레임 관찰', '100ミリ秒後のフレームを観察'],
  step: ['+0.1초', '+0.1秒'],
  rotate: ['회전', '回転'],
  zoomOut: ['장면 축소', 'シーンを縮小'],
  zoomIn: ['장면 확대', 'シーンを拡大'],
  reset: ['시점 초기화', '視点をリセット'],
  canvas: ['실제 에셋과 배치를 사용한 게임 장면', '実際のアセットと配置を使ったゲームシーン'],
  assetDetail: ['선택한 에셋 검사', '選択したアセットを検査'],
  assetLibrary: ['에셋 보관함', 'アセット一覧'],
  runAssets: ['실행 에셋', '実行アセット'],
  gameBrief: ['기록된 게임 기획', '記録されたゲーム企画'],
  steps: ['제작 단계', '制作工程'],
  searchPlaceholder: ['이름, 파일 경로, ID 검색', '名前、ファイルパス、ID を検索'],
  searchGraph: ['그래프 항목 검색', 'グラフ項目を検索'],
  graphType: ['그래프 항목 종류', 'グラフ項目の種類'],
  allTypes: ['모든 종류', 'すべての種類'],
  revisionExplanation: ['상태 리비전은 실행 순서 기록이며 제작 인과와 구분합니다.', '状態リビジョンは実行順の記録であり、制作の因果関係とは区別されます。'],
  connectionGraph: ['선택한 항목의 연결 그래프', '選択した項目の接続グラフ'],
  graphNodes: ['그래프 항목', 'グラフ項目'],
  rawProperties: ['원본 JSON-LD 속성', '元の JSON-LD プロパティ'],
  language: ['언어', '言語'],
  languagePicker: ['화면 언어', '表示言語'],
};

function localizeShell() {
  for (const [attribute, target] of [['data-i18n', null], ['data-i18n-aria-label', 'aria-label'], ['data-i18n-placeholder', 'placeholder']]) {
    for (const element of document.querySelectorAll(`[${attribute}]`)) {
      const value = t(copy, element.getAttribute(attribute));
      if (target) element.setAttribute(target, value);
      else element.textContent = value;
    }
  }
  document.getElementById('language-picker').value = getLocale();
}

localizeShell();
document.getElementById('language-picker').addEventListener('change', event => setLocale(event.target.value));
window.addEventListener('studio:localechange', localizeShell);
