import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareRecords, latestCriterionResult, criterionResults, activeReviewEvidence } from './compare.mjs';
import { compareMessages } from './compare-messages.mjs';

const comparison = (id, recordedAt) => ({ '@id': id, '@type': ['Entity', 'ReviewComparison'], recordedAt, snapshot: { id, a: {}, b: {}, criteria: [] } });
const evidence = (id, comparison, run, status, recordedAt) => ({ '@id': id, '@type': ['Entity', 'ReviewEvidence'], recordedAt,
  snapshot: { comparison, run, actor: 'reviewer', results: [{ criterion: 'timing', status, reason: id, evidence: [] }] } });

test('comparison projection keeps latest records and only their recorded evidence/decisions', () => {
  const a = comparison('old', '2026-11-01'), b = comparison('new', '2026-11-02');
  const nodes = [a, b, evidence('first', 'new', 'A', 'pass', '2026-11-02'), evidence('latest', 'new', 'A', 'fail', '2026-11-03'),
    evidence('other-side', 'new', 'B', 'pending', '2026-11-04'), evidence('unrelated', 'old', 'A', 'pass', '2026-11-05'),
    { '@id': 'decision', '@type': ['Entity', 'ReviewDecision'], snapshot: { comparison: 'new' } }];
  const records = compareRecords({ '@graph': nodes });
  assert.equal(records[0].node['@id'], 'new');
  assert.equal(records[0].decisions.length, 1);
  assert.equal(latestCriterionResult(records[0].evidence, 'timing', 'A').status, 'fail');
  assert.equal(latestCriterionResult(records[0].evidence, 'timing', 'B').status, 'pending');
  assert.equal(latestCriterionResult(records[0].evidence, 'missing', 'A'), null);
  assert.equal(nodes[0], a);
  assert.deepEqual(compareRecords(null), []);
});

test('compare copy covers KO/JA without interpolated markup', () => {
  for (const [key, pair] of Object.entries(compareMessages)) {
    assert.equal(pair.length, 2, key);
    assert.ok(pair.every(value => value.trim()), key);
    assert.deepEqual([...pair[0].matchAll(/\{(\w+)\}/g)].map(m => m[1]), [...pair[1].matchAll(/\{(\w+)\}/g)].map(m => m[1]), key);
  }
});


test('active failures and pending remain visible beside later passes until explicitly superseded', () => {
  const failure = evidence('fail', 'compare', 'A', 'fail', '2026-11-01');
  const passing = evidence('pass', 'compare', 'A', 'pass', '2026-11-02');
  assert.deepEqual(criterionResults([passing, failure], 'timing', 'A').map(r => r.status), ['pass', 'fail']);
  passing.snapshot.supersedes = ['fail'];
  passing.snapshot.resolution_reason = 'Observed the fixed timing';
  assert.deepEqual(activeReviewEvidence([passing, failure]), [passing]);
  const result = criterionResults([passing, failure], 'timing', 'A');
  assert.equal(result.length, 1);
  assert.equal(result[0].resolution_reason, 'Observed the fixed timing');
  assert.deepEqual(result[0].supersedes, ['fail']);
});
