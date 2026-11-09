import {loadCampaign} from './campaign.mjs';
import {createFeedback} from './feedback.mjs';

const symbols = {circle: '●', diamond: '◆', triangle: '▲'};
const names = {circle: '동그라미', diamond: '마름모', triangle: '세모'};
const signals = [['circle', 'diamond'], ['diamond', 'circle', 'triangle']];
const $ = id => document.getElementById(id);
const keys = [...document.querySelectorAll('[data-symbol]')];

try {
  const campaign = await loadCampaign();
  const feedback = createFeedback();
  let entered = [];
  const target = () => campaign.index === 0 ? signals[0] : [...signals[1]].reverse();

  function render(message) {
    const playing = campaign.phase === 'playing';
    $('stage-number').textContent = `작업 ${campaign.index + 1} / ${signals.length}`;
    $('stage-title').textContent = campaign.stage.title;
    $('objective').textContent = campaign.stage.objective;
    $('tactic').textContent = campaign.stage.tactic;
    $('device').textContent = campaign.index === 0
      ? '중계기 · 표시된 순서 그대로 →' : '새 장치: 고장 난 거울 · 반대 순서로 ←';
    $('signal').replaceChildren(...signals[campaign.index].map(symbol => {
      const item = document.createElement('li');
      item.textContent = symbols[symbol];
      item.setAttribute('aria-label', names[symbol]);
      return item;
    }));
    $('answer').replaceChildren(...target().map((expected, index) => {
      const item = document.createElement('li');
      const symbol = entered[index];
      item.textContent = symbol ? symbols[symbol] : index === entered.length && playing ? '↓' : '·';
      item.className = symbol ? symbol === expected ? 'correct' : 'wrong'
        : index === entered.length && playing ? 'current' : '';
      item.setAttribute('aria-label', `${index + 1}번째: ${symbol ? names[symbol] : '입력 대기'}`);
      return item;
    }));
    const correct = entered.filter((symbol, index) => symbol === target()[index]).length;
    $('progress').textContent = `복구 진행 ${correct} / ${target().length} · ${playing
      ? `다음 입력 ${entered.length + 1}번째` : campaign.phase === 'failed' ? '연결 끊김' : '연결 완료'}`;
    keys.forEach(button => { button.disabled = !playing || campaign.index === 0 && button.dataset.symbol === 'triangle'; });
    $('retry').hidden = campaign.phase !== 'failed';
    $('next').hidden = campaign.phase !== 'between';
    $('restart').disabled = false;
    $('status').textContent = message;
  }

  function present(name) {
    const cue = feedback.emit(name);
    const slot = $('answer').children[entered.length - 1];
    slot.dataset.cue = name;
    if (!cue.enabled || cue.reducedMotion) return;
    const frames = name === 'denied' ? ['translateX(0)', 'translateX(-4px)', 'translateX(3px)', 'translateX(0)']
      : ['scale(1)', 'scale(1.12)', 'scale(1)'];
    slot.animate(frames.map(transform => ({transform})), {duration: 180, easing: 'ease-out'});
  }

  keys.forEach(button => button.addEventListener('click', () => {
    if (campaign.phase !== 'playing') return;
    const symbol = button.dataset.symbol;
    const expected = target()[entered.length];
    entered.push(symbol);
    if (symbol !== expected) {
      campaign.failStage();
      render(`${symbols[symbol]} 신호 오류! ${entered.length}번째 연결이 끊겼습니다. 이 단계에서 다시 시도하세요.`);
      present('denied');
      $('retry').focus();
    } else if (entered.length === target().length) {
      campaign.finishStage();
      render(campaign.phase === 'complete' ? '공방 작업 완료! 두 장치를 모두 복구했습니다.'
        : '중계기 복구 성공! 계속 버튼을 눌러 다음 장치를 살펴보세요.');
      present(campaign.phase === 'complete' ? 'finish' : 'progress');
      (campaign.phase === 'complete' ? $('restart') : $('next')).focus();
    } else {
      render(`${symbols[symbol]} 수신 완료! ${entered.length}번째 연결 성공. 다음 기호를 입력하세요.`);
      present('select');
    }
  }));

  function begin(message) {
    entered = [];
    render(message);
    keys[0].focus();
  }
  $('sound').addEventListener('click', () => {
    const state = feedback.setSound(!feedback.sound);
    $('sound').textContent = state === 'unavailable' ? '소리 재생 불가' : feedback.sound ? '소리 켜짐' : '소리 꺼짐';
    $('sound').setAttribute('aria-pressed', String(feedback.sound && state !== 'unavailable'));
  });
  $('retry').addEventListener('click', () => {
    if (campaign.retry()) begin('같은 장치에서 다시 시작합니다. 신호 순서를 살펴보세요.');
  });
  $('next').addEventListener('click', () => {
    if (campaign.advance()) begin('거울 장치가 들어왔습니다. 이번에는 표시 신호를 역순으로 전달하세요.');
  });
  $('restart').addEventListener('click', () => {
    campaign.restart();
    begin('작업을 초기화했습니다. 첫 번째 중계기부터 연결하세요.');
  });
  render('첫 번째 신호부터 같은 순서로 전달하세요.');
} catch {
  $('stage-title').textContent = '공방을 열 수 없습니다';
  $('status').textContent = '캠페인 파일을 불러오지 못했습니다. 내보낸 게임을 웹 서버에서 열고 다시 시도하세요.';
}
