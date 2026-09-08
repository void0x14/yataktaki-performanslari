import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { checkedResponse, mergeEvents, eventCursor, evidenceImageRef } from '../app/src/observability.ts';

test('a rejected command cannot be displayed as completed', () => {
  assert.throws(() => checkedResponse({ok: false, error: 'agent_not_found', detail: 'missing'}), /agent_not_found.*missing/);
  assert.throws(() => checkedResponse(null), /yanıt/);
  assert.throws(() => checkedResponse({}), /yanıt/);
  assert.equal(checkedResponse({ok: true, agents: []}).ok, true);
});

test('replay merges only the selected agent, removes duplicates and orders by sequence', () => {
  const events = mergeEvents([{agent_id:'a', seq:2, event_id:'two'}], [
    {agent_id:'b', seq:3, event_id:'other'},
    {agent_id:'a', seq:4, event_id:'four'},
    {agent_id:'a', seq:2, event_id:'two'},
    {agent_id:'a', seq:1, event_id:'one'},
  ], 'a');
  assert.deepEqual(events.map(e => e.seq), [1,2,4]);
  assert.equal(eventCursor(events), 4);
  assert.equal(eventCursor([]), 0);
});

test('bounded history retains the newest events', () => {
  const rows = Array.from({length:300}, (_,seq) => ({seq:seq+1, agent_id:'a', event_id:String(seq)}));
  const result = mergeEvents([], rows, 'a');
  assert.equal(result.length, 250);
  assert.equal(result[0].seq, 51);
  assert.equal(eventCursor(result), 300);
});


test('Kahin OCR screenshot is a visible evidence image', () => {
  const event = {
    evidence_refs: [
      'agent://a/outputs/source-00001.txt',
      'agent://a/outputs/kahin-myip-00001.png',
    ],
  };
  assert.equal(evidenceImageRef(event), 'agent://a/outputs/kahin-myip-00001.png');
  assert.equal(evidenceImageRef({frame_ref:'agent://a/frames/0001.png'}), 'agent://a/frames/0001.png');
  assert.equal(evidenceImageRef({evidence_refs:['agent://a/outputs/source.txt']}), '');
});
