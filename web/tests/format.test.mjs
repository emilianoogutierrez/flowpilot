import test from 'node:test';
import assert from 'node:assert/strict';
import { duration, initials, label, nodesByDepth } from '../dist/assets/format.js';

test('duration distinguishes milliseconds, seconds and minutes', () => {
  assert.equal(duration(null), '—');
  assert.equal(duration(25.1), '25 ms');
  assert.equal(duration(1200), '1.20 s');
  assert.equal(duration(90000), '1m 30s');
});

test('labels and initials are deterministic', () => {
  assert.equal(label('awaiting_approval'), 'Awaiting approval');
  assert.equal(initials('Demo User'), 'DU');
  assert.equal(initials('   '), '');
});

test('graph depth handles shuffled definitions', () => {
  const result = nodesByDepth([{id: 'c', depends_on: ['a', 'b']}, {id: 'a'}, {id: 'b', depends_on: ['a']}]);
  assert.equal(result.get('c'), 2);
});

test('graph rejects a cycle instead of looping', () => {
  assert.throws(() => nodesByDepth([{id: 'a', depends_on: ['b']}, {id: 'b', depends_on: ['a']}]));
});
