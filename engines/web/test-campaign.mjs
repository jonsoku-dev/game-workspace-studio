import assert from 'node:assert/strict';
import {createCampaign, loadCampaign} from './campaign.mjs';

const stages = ['first', 'second', 'third'].map(id => ({id, title: id, objective: 'Exit', tactic: 'Wait'}));
const campaign = createCampaign(stages);
const initial = campaign.stage;
assert.equal(campaign.index, 0);
assert.equal(campaign.phase, 'playing');
assert.equal(campaign.advance(), false);
assert.equal(campaign.retry(), false);
stages[0].title = 'mutated';
stages.reverse();
assert.equal(initial.title, 'first');
assert.throws(() => { initial.title = 'mutated'; }, TypeError);
for (const property of ['index', 'stage', 'phase']) {
  assert.throws(() => { campaign[property] = null; }, TypeError);
}
assert.equal(campaign.failStage(), true);
assert.equal(campaign.failStage(), false);
assert.equal(campaign.phase, 'failed');
assert.equal(campaign.finishStage(), false);
assert.equal(campaign.advance(), false);
assert.equal(campaign.retry(), true);
assert.equal(campaign.index, 0);
assert.equal(campaign.stage, initial);
assert.equal(campaign.finishStage(), true);
assert.equal(campaign.phase, 'between');
assert.equal(campaign.finishStage(), false);
assert.equal(campaign.failStage(), false);
assert.equal(campaign.retry(), false);
assert.equal(campaign.advance(), true);
assert.equal(campaign.index, 1);
assert.equal(campaign.stage.id, 'second');
assert.equal(campaign.failStage(), true);
assert.equal(campaign.retry(), true);
assert.equal(campaign.index, 1);
assert.equal(campaign.advance(), false);
assert.equal(initial.id, 'first');
assert.equal(campaign.finishStage(), true);
assert.equal(campaign.advance(), true);
assert.equal(campaign.index, 2);
assert.equal(campaign.finishStage(), true);
assert.equal(campaign.phase, 'complete');
for (const action of ['finishStage', 'advance', 'failStage', 'retry']) assert.equal(campaign[action](), false);
assert.equal(campaign.index, 2);
for (const phase of ['complete', 'playing', 'failed', 'between']) {
  if (phase === 'failed') campaign.failStage();
  if (phase === 'between') campaign.finishStage();
  assert.equal(campaign.phase, phase);
  assert.equal(campaign.restart(), true);
  assert.equal(campaign.index, 0);
  assert.equal(campaign.phase, 'playing');
}

const valid = ['one', 'two'].map(id => ({id, title: 'Title', objective: 'Exit', tactic: 'Wait'}));
for (const invalid of [null, {}, [], valid.slice(0, 1), Array(33).fill(valid[0]),
  [valid[0], valid[0]], [null, valid[1]], [{...valid[0], extra: true}, valid[1]],
  ...['Upper', 'a\n', 'a--b', 'é', 'a'.repeat(65)].map(id => [{...valid[0], id}, valid[1]]),
  ...['', ' ', 1, 'x'.repeat(4001)].map(title => [{...valid[0], title}, valid[1]])]) {
  assert.throws(() => createCampaign(invalid), TypeError);
}
const maximum = Array.from({length: 32}, (_, index) => ({...valid[0], id: `stage-${index}`}));
assert.equal(createCampaign(maximum).index, 0);
assert.equal(createCampaign([{...valid[0], id: 'a'.repeat(64), title: '😀'.repeat(4000)}, valid[1]]).index, 0);

const originalFetch = globalThis.fetch;
try {
  globalThis.fetch = async url => {
    assert.equal(url.href, new URL('./genre.json', import.meta.url).href);
    return {ok: true, json: async () => ({stages: valid})};
  };
  assert.equal((await loadCampaign()).stage.id, 'one');
  globalThis.fetch = async () => ({ok: false, status: 404, json: () => assert.fail('Read failed response')});
  await assert.rejects(loadCampaign(), /404/);
  globalThis.fetch = async () => { throw new Error('offline'); };
  await assert.rejects(loadCampaign(), /offline/);
  globalThis.fetch = async () => ({ok: true, json: async () => { throw new SyntaxError('bad JSON'); }});
  await assert.rejects(loadCampaign(), SyntaxError);
  globalThis.fetch = async () => ({ok: true, json: async () => ({})});
  await assert.rejects(loadCampaign(), TypeError);
} finally {
  globalThis.fetch = originalFetch;
}
console.log('Campaign lifecycle and loading checks passed');
