import assert from 'node:assert/strict';
import test from 'node:test';
import { describe9RouterVideo } from '../dist/transport.js';

const VIDEO = Buffer.alloc(2048, 1);
const base = { buffer: VIDEO, mime: 'video/mp4', baseUrl: 'https://router.example/v1', apiKey: 'secret-test', model: 'openclaw' };

test('forwards MP4 through tested image_url data URI compatibility path', async () => {
  let observed;
  const result = await describe9RouterVideo({ ...base, fetchFn: async (url, options) => {
    observed = { url, options };
    return new Response(JSON.stringify({ model: 'gemini-test', choices: [{ message: { content: 'Presenter berdiri dekat mobil.' }}]}), { status: 200, headers: {'content-type':'application/json'} });
  }});
  assert.equal(observed.url, 'https://router.example/v1/chat/completions');
  const body = JSON.parse(observed.options.body);
  assert.equal(body.model, 'openclaw');
  assert.equal(body.messages[0].content[1].type, 'image_url');
  assert.equal(body.messages[0].content[1].image_url.url, `data:video/mp4;base64,${VIDEO.toString('base64')}`);
  assert.equal(result.text, 'Presenter berdiri dekat mobil.');
  assert.equal(result.model, 'gemini-test');
});

test('rejects oversized input without making network request', async () => {
  await assert.rejects(describe9RouterVideo({...base, buffer: Buffer.alloc(21*1024*1024)}), /20 MiB/);
});

test('rejects missing credentials', async () => {
  await assert.rejects(describe9RouterVideo({...base, apiKey: ''}), /API key/);
});

test('rejects failed upstream response without leaking payload', async () => {
  await assert.rejects(describe9RouterVideo({...base, fetchFn: async () => new Response('SECRET', {status: 400})}), /^Error: 9Router video request failed: HTTP 400$/);
});
