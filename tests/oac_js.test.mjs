import test from 'node:test';
import assert from 'node:assert/strict';
import { createPrivateKey, createPublicKey } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import {
  canonicalBody,
  signEvent,
  verificationReceipt,
  verifyEvent,
} from '../clients/oac_js.mjs';

const seed = Buffer.from('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f', 'hex');
const body = {
  v: '0.1', type: 'problem',
  author: 'ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg',
  time: 1789872000, topic: ['mathematics'],
  text: 'Can X be proven more simply?', refs: [],
};
const expectedJcs = '{"author":"ed25519:A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg","refs":[],"text":"Can X be proven more simply?","time":1789872000,"topic":["mathematics"],"type":"problem","v":"0.1"}';
const expectedId = '5650b457ce6d580e6e62a9d02ee42087198f45d383d1c65a6bffa59d3e04a8f6';
const expectedSig = 'cxngzRwa_Ao2B8LnKDajsO4uF_0Za_QvhNUB1NmncQ1zzGNhSZgrC6oiDEyFVMFFhFWce1TzKKIQh6WVZ_QhDQ';

test('Genesis JCS, Event ID, and Ed25519 vector', () => {
  assert.equal(canonicalBody(body).toString(), expectedJcs);
  const event = signEvent(body, seed);
  assert.equal(event.id, expectedId);
  assert.equal(event.sig, expectedSig);
  assert.equal(verifyEvent(event), event);
});

test('tampering and malformed Unicode are rejected', () => {
  const event = signEvent(body, seed);
  assert.throws(() => verifyEvent({ ...event, text: 'tampered' }), { code: 'invalid_event_id' });
  assert.throws(() => canonicalBody({ ...body, text: '\ud800' }), { code: 'invalid_event' });
});

test('verification receipt separates retrieval, content ID, and signature checks', () => {
  const event = signEvent(body, seed);
  const receipt = verificationReceipt(event, {
    source: 'https://node.example',
    observedAt: '2026-10-18T00:00:00.000Z',
    expectedEventId: expectedId,
  });
  assert.deepEqual(receipt, {
    profile: 'oac-verification-receipt/0.1',
    target_event_id: expectedId,
    observed_event_id: expectedId,
    source: 'https://node.example',
    observed_at: '2026-10-18T00:00:00.000Z',
    implementation: { name: 'oac_js.mjs', version: 'unreleased-receipt-v0.1' },
    checks: { retrieval: 'pass', content_id: 'pass', signature: 'pass' },
    status: 'pass',
    errors: [],
  });

  const wrongId = verificationReceipt({ ...event, id: '0'.repeat(64) });
  assert.equal(wrongId.checks.retrieval, 'not-tested');
  assert.equal(wrongId.checks.content_id, 'fail');
  assert.equal(wrongId.checks.signature, 'pass');
  assert.equal(wrongId.status, 'fail');
  assert.deepEqual(wrongId.errors, ['invalid_event_id']);

  const tampered = verificationReceipt({ ...event, text: 'tampered' });
  assert.equal(tampered.checks.content_id, 'fail');
  assert.equal(tampered.checks.signature, 'fail');
  assert.equal(tampered.status, 'fail');
  assert.deepEqual(tampered.errors, ['invalid_event_id', 'invalid_signature']);
});

test('receipt CLI returns status 2 after printing a failed offline receipt', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'oac-receipt-'));
  const path = join(directory, 'tampered.json');
  try {
    await writeFile(path, JSON.stringify({ ...signEvent(body, seed), text: 'tampered' }));
    const client = fileURLToPath(new URL('../clients/oac_js.mjs', import.meta.url));
    const result = spawnSync(process.execPath, [client, 'receipt', path], { encoding: 'utf8' });
    assert.equal(result.status, 2);
    assert.equal(result.stderr, '');
    const receipt = JSON.parse(result.stdout);
    assert.equal(receipt.status, 'fail');
    assert.equal(receipt.checks.content_id, 'fail');
    assert.equal(receipt.checks.signature, 'fail');
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('Node Ed25519 raw public key framing matches the vector author', () => {
  const privateKey = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der', type: 'pkcs8',
  });
  const spki = createPublicKey(privateKey).export({ format: 'der', type: 'spki' });
  assert.equal(`ed25519:${spki.subarray(-32).toString('base64url')}`, body.author);
});
