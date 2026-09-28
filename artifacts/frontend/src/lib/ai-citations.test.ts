import assert from 'node:assert/strict';
import test from 'node:test';
import { answerSourceResults, citationHref, isAssetLevelCitation, mediaLookupState, groupCitations, momentHref, formatTimecode, latestSourceAnswer, mergeMessages, pendingPersisted } from './ai-citations.ts';

const c = (media_id: string, start_time: number, snippet = '') => ({ media_id, filename: `${media_id}.mp4`, start_time, end_time: start_time + 5, snippet });

test('groups duplicate media citations, keeps order and source numbers', () => {
  const g = groupCitations([c('b', 90), c('a', 10), c('b', 12), c('b', 90.4)]);
  assert.deepEqual(g.map(x => x.mediaId), ['b', 'a']);
  assert.deepEqual(g[0].moments.map(m => [m.start_time, m.index]), [[12, 3], [90, 1]]);
  assert.equal(groupCitations(null).length, 0);
});

test('latest answer citations become library cards without a search, including asset-level hits', () => {
  const results = answerSourceResults([c('b', 90, 'later'), c('a', 10), c('b', 12, 'earlier'), c('b', 90.4), {
    media_id: 'metadata', filename: 'metadata.mp4', start_time: 0, end_time: 0, snippet: 'Original air date: May 3, 1992',
  }]);
  assert.deepEqual(results.map(r => [r.media_id, r.start_time, r.match_type]), [
    ['b', 12, 'source'], ['b', 90, 'source'], ['a', 10, 'source'], ['metadata', 0, 'metadata'],
  ]);
  assert.equal(results[0].snippet, 'earlier');
  assert.equal(results[3].snippet, 'Original air date: May 3, 1992');
  assert.deepEqual(answerSourceResults([]), []);
  assert.deepEqual(answerSourceResults(null), []);
});

test('conversation turns preserve the latest search, including an explicit empty search', () => {
  const airdate = { role: 'assistant', content: 'Original air date', citations: [c('airdate', 0)] };
  const scope = { role: 'assistant', content: 'I mean original broadcast date.', citations: null };
  const messages = [airdate, { role: 'user', content: 'What does airdate mean?' }, scope];
  assert.deepEqual(latestSourceAnswer(messages), { index: 0, message: airdate });
  assert.deepEqual(answerSourceResults(latestSourceAnswer(messages)!.message.citations).map(r => r.media_id), ['airdate']);
  assert.deepEqual(latestSourceAnswer([{ role: 'assistant', content: 'Hello', citations: null }]), null);
  const empty = { role: 'assistant', content: 'No matching sources', citations: [] };
  assert.deepEqual(latestSourceAnswer([...messages, empty, scope]), { index: 3, message: empty });
  assert.deepEqual(answerSourceResults(latestSourceAnswer([...messages, empty, scope])!.message.citations), []);
  const fresh = { role: 'assistant', content: 'Found another', citations: [c('new', 15)] };
  assert.deepEqual(latestSourceAnswer([...messages, empty, scope, fresh]), { index: 5, message: fresh });
});

test('moment links target the player with whole seconds', () => {
  assert.equal(momentHref('abc', 83.7), '/library/abc?t=83');
  assert.equal(momentHref('a b', -4), '/library/a%20b?t=0');
  assert.equal(formatTimecode(3725), '1:02:05');
  assert.equal(formatTimecode(65), '1:05');
});

test('optimistic reply survives until persisted copy exists', () => {
  const pending = [{ role: 'user', content: 'q' }, { role: 'assistant', content: 'a' }];
  assert.equal(mergeMessages([], pending).length, 2);
  // stale fetch with only the user turn: assistant must still render
  const partial = [{ role: 'user', content: 'q' }];
  assert.deepEqual(mergeMessages(partial, pending).map(m => m.content), ['q', 'a']);
  assert.equal(pendingPersisted(partial, pending), false);
  assert.equal(pendingPersisted([...partial, { role: 'assistant', content: 'a' }], pending), true);
});

test('repeated identical questions are not swallowed by older history', () => {
  const saved = [{ role: 'user', content: 'again' }, { role: 'assistant', content: 'x' }];
  const pending = [{ role: 'user', content: 'again' }];
  assert.equal(mergeMessages(saved, pending, 2).length, 3);
  assert.equal(mergeMessages([...saved, { role: 'user', content: 'again' }], pending, 2).length, 3);
});

test('metadata 0-0 citations open the asset, not a 0:00 moment', () => {
  assert.equal(isAssetLevelCitation({ start_time: 0, end_time: 0 }), true);
  assert.equal(isAssetLevelCitation({ start_time: 0, end_time: 4 }), false);
  assert.equal(citationHref('a', { start_time: 0, end_time: 0 }), '/library/a');
  assert.equal(citationHref('a', { start_time: 12, end_time: 20 }), '/library/a?t=12');
});

test('only 404/410 lookups count as unavailable', () => {
  assert.equal(mediaLookupState({ status: 404 }), 'missing');
  assert.equal(mediaLookupState({ status: 500 }), 'transient');
  assert.equal(mediaLookupState(new TypeError('Failed to fetch')), 'transient');
});
