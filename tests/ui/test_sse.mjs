import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const code = await readFile(new URL('../../app/ui/static/sse.js', import.meta.url), 'utf8');
const { parseSSE } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

function stream(parts) {
  return new ReadableStream({ start(controller) { for (const part of parts) controller.enqueue(part); controller.close(); } });
}

test('SSE parser handles byte boundaries, UTF-8, CRLF and heartbeats', async () => {
  const text = ': heartbeat\r\n\r\nevent: answer_delta\r\ndata: "caf?"\r\n\r\nevent: final\ndata: {"cached":false}\n\n';
  const bytes = new TextEncoder().encode(text);
  const events = [];
  await parseSSE(stream([...bytes].map(x => Uint8Array.of(x))), (...event) => events.push(event));
  assert.deepEqual(events, [['answer_delta', 'caf?'], ['final', { cached: false }]]);
});

test('SSE parser handles multiline data, comments and incomplete frames', async () => {
  const text = 'event: final\ndata: {\n: comment\ndata: "answer":"ok"}\n\nevent: final\ndata: "incomplete"';
  const events = [];
  await parseSSE(stream([new TextEncoder().encode(text)]), (...event) => events.push(event));
  assert.deepEqual(events, [['final', { answer: 'ok' }]]);
});

test('SSE parser propagates invalid JSON and releases its reader', async () => {
  const source = stream([new TextEncoder().encode('data: bad\n\n')]);
  await assert.rejects(parseSSE(source, () => {}), SyntaxError);
  assert.equal(source.locked, false);
});
