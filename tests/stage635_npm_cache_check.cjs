// Offline TEST_ONLY check of the actual npm cache consumer, not a live request.
// Usage: node tests/stage635_npm_cache_check.cjs /path/to/node_modules/npm
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(process.argv[2]);
const CachePolicy = require(path.join(root, 'node_modules/make-fetch-happen/lib/cache/policy.js'));
const { Request, Response } = require(path.join(root, 'node_modules/minipass-fetch'));
const CacheSemantics = require(path.join(root, 'node_modules/http-cache-semantics'));

const request = new Request('https://example.invalid/test-only', {
  headers: { 'cache-control': 'max-stale=999999' },
});
const response = new Response('TEST_ONLY', {
  status: 200,
  headers: { 'set-cookie': 'TEST_ONLY=fixture', 'cache-control': 'max-age=0' },
});
const options = { cachePath: '/tmp/TEST_ONLY-not-created' };
const npmPolicy = new CachePolicy({ request, response, options });
assert.equal(npmPolicy.policy._isShared, false);
assert.equal(CachePolicy.storable(request, { ...options, cache: 'no-store' }), false);

// GHSA-ch52-4w7c-c8xp is disputed by upstream. Version 4.3.0 falls outside
// the advisory range, but still reproduces the reported shared-cache behavior.
// Do not misreport a clean npm audit as a behavioral patch.
const req = { url: request.url, method: 'GET', headers: { host: 'example.invalid' } };
const shared = new CacheSemantics(req, {
  status: 200,
  headers: { 'cache-control': 'max-age=0', 'set-cookie': 'TEST_ONLY=fixture' },
}, { shared: true });
assert.equal(shared.maxAge(), 0);
const disputed = shared.satisfiesWithoutRevalidation({
  ...req, headers: { ...req.headers, 'cache-control': 'max-stale=999999' },
});
const privatePolicy = new CacheSemantics(req, {
  status: 200,
  headers: { 'cache-control': 'private,no-store', 'set-cookie': 'TEST_ONLY=fixture' },
}, { shared: true });
assert.equal(privatePolicy.storable(), false);
console.log(JSON.stringify({ status: 'PASS', npm_shared_cache: false,
  no_store_not_cached: true, private_no_store_not_storable: true,
  disputed_shared_max_stale_reproduces: disputed, network_requests: 0 }));
