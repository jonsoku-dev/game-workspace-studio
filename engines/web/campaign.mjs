export function createCampaign(stages) {
  if (!Array.isArray(stages) || stages.length < 2 || stages.length > 32) {
    throw new TypeError('Campaign requires 2 to 32 stages');
  }
  const ids = new Set();
  const ordered = Object.freeze(Array.from(stages, stage => {
    if (!stage || typeof stage !== 'object' || Array.isArray(stage)
        || Object.keys(stage).sort().join(',') !== 'id,objective,tactic,title'
        || typeof stage.id !== 'string' || stage.id.length > 64
        || stage.id.match(/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/)?.[0] !== stage.id || ids.has(stage.id)
        || ['title', 'objective', 'tactic'].some(key => typeof stage[key] !== 'string'
          || !stage[key].trim() || Array.from(stage[key]).length > 4000)) {
      throw new TypeError('Expected unique stage slugs and bounded title, objective and tactic strings');
    }
    ids.add(stage.id);
    return Object.freeze({id: stage.id, title: stage.title, objective: stage.objective, tactic: stage.tactic});
  }));
  let index = 0, phase = 'playing';
  const campaign = Object.freeze({
    get index() { return index; },
    get stage() { return ordered[index]; },
    get phase() { return phase; },
    finishStage() {
      if (phase !== 'playing') return false;
      phase = index === ordered.length - 1 ? 'complete' : 'between';
      return true;
    },
    advance() {
      if (phase !== 'between') return false;
      index++;
      phase = 'playing';
      return true;
    },
    failStage() {
      if (phase !== 'playing') return false;
      phase = 'failed';
      return true;
    },
    retry() {
      if (phase !== 'failed') return false;
      phase = 'playing';
      return true;
    },
    restart() {
      index = 0;
      phase = 'playing';
      return true;
    },
    confirmResult() {
      if (phase === 'between') {
        campaign.advance();
        return 'advance';
      }
      if (phase === 'failed') {
        campaign.retry();
        return 'retry';
      }
      if (phase === 'complete') {
        campaign.restart();
        return 'restart';
      }
      return null;
    },
  });
  return campaign;
}

export async function loadCampaign() {
  const response = await fetch(new URL('./genre.json', import.meta.url));
  if (!response.ok) throw new Error(`Campaign manifest request failed (${response.status})`);
  const manifest = await response.json();
  return createCampaign(manifest?.stages);
}
