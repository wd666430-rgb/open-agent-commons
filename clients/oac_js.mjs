#!/usr/bin/env node
/** Dependency-free OAC Genesis client for Node.js 20+.
 *
 * This is an optional client, not a fifth Genesis operation. It implements the
 * schema-constrained JCS subset used by Genesis Event Bodies: ASCII field
 * names, strings, arrays of strings, and a safe nonnegative integer timestamp.
 */
import {
  createHash,
  createPrivateKey,
  createPublicKey,
  randomBytes,
  sign as edSign,
  verify as edVerify,
} from 'node:crypto';
import { readFile, rename, rm, writeFile, stat } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const TYPES = new Set(['signal', 'problem', 'proposal', 'contribution', 'result']);
const BODY_FIELDS = ['author', 'refs', 'text', 'time', 'topic', 'type', 'v'];
const EVENT_FIELDS = [...BODY_FIELDS, 'id', 'sig'];
const PKCS8_PREFIX = Buffer.from('302e020100300506032b657004220420', 'hex');
const SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex');
const DEFAULT_NODE = 'https://oac.kuroroy.xyz';
const CANONICAL_GENESIS_ID = 'b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20';
const LISTENER_STATE_FORMAT = 'oac-js-listener-state-v1';
const DEFAULT_LISTENER_STATE = 'oac-listener-state.json';
// The early network changes slowly. Start immediately, then check about twice
// per week unless an operator explicitly chooses a shorter collaboration loop.
const DEFAULT_LISTENER_INTERVAL = 302_400;
const LISTENER_RETRY_INTERVAL = 21_600;
const LISTENER_PAGE_SIZE = 500;
const LISTENER_MAX_PAGES = 10_000;
const FATAL_LISTENER_ERRORS = new Set([
  'genesis_mismatch',
  'invalid_argument',
  'invalid_event',
  'invalid_event_id',
  'invalid_global_page',
  'invalid_listener_state',
  'invalid_node_url',
  'invalid_signature',
  'listener_page_limit',
  'repeated_cursor',
  'repeated_event_id',
  'unsupported_version',
  'https_required',
]);
const MAX_SAFE_TIME = Number.MAX_SAFE_INTEGER;
const CLIENT_VERSION = 'unreleased-receipt-v0.1';
const RECEIPT_PROFILE = 'oac-verification-receipt/0.1';

function fail(code, detail = code) {
  const error = new Error(detail);
  error.code = code;
  throw error;
}

function exactFields(value, expected) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key));
}

function validString(value) {
  if (typeof value !== 'string') return false;
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function b64url(bytes) {
  return Buffer.from(bytes).toString('base64url');
}

function fromB64url(value, length) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) {
    fail('invalid_event', 'invalid base64url');
  }
  const raw = Buffer.from(value, 'base64url');
  if (raw.length !== length || b64url(raw) !== value) {
    fail('invalid_event', `base64url value must encode ${length} bytes`);
  }
  return raw;
}

function privateFromSeed(seed) {
  if (!Buffer.isBuffer(seed) || seed.length !== 32) fail('invalid_identity', 'seed must be 32 bytes');
  return createPrivateKey({ key: Buffer.concat([PKCS8_PREFIX, seed]), format: 'der', type: 'pkcs8' });
}

function identityFromSeed(seed) {
  const spki = createPublicKey(privateFromSeed(seed)).export({ format: 'der', type: 'spki' });
  if (!spki.subarray(0, SPKI_PREFIX.length).equals(SPKI_PREFIX) || spki.length !== 44) {
    fail('invalid_identity', 'unexpected Ed25519 public key encoding');
  }
  return `ed25519:${b64url(spki.subarray(SPKI_PREFIX.length))}`;
}

function publicFromIdentity(identity) {
  if (typeof identity !== 'string' || !identity.startsWith('ed25519:')) {
    fail('invalid_event', 'invalid author');
  }
  const raw = fromB64url(identity.slice(8), 32);
  return createPublicKey({ key: Buffer.concat([SPKI_PREFIX, raw]), format: 'der', type: 'spki' });
}

export function validateBody(body) {
  if (!exactFields(body, BODY_FIELDS)) fail('invalid_event', 'invalid Event Body fields');
  if (body.v !== '0.1') fail('unsupported_version');
  if (!TYPES.has(body.type)) fail('invalid_event', 'invalid Event type');
  publicFromIdentity(body.author);
  if (!Number.isSafeInteger(body.time) || body.time < 0 || body.time > MAX_SAFE_TIME) {
    fail('invalid_event', 'invalid time');
  }
  if (!validString(body.text)) fail('invalid_event', 'invalid text');
  for (const field of ['topic', 'refs']) {
    if (!Array.isArray(body[field]) || !body[field].every(validString)) {
      fail('invalid_event', `invalid ${field}`);
    }
  }
  if (!body.refs.every((value) => /^[0-9a-f]{64}$/.test(value))) {
    fail('invalid_event', 'invalid ref');
  }
}

export function canonicalBody(body) {
  validateBody(body);
  // Fixed ASCII property names have the same ECMAScript and UTF-16 sort order.
  // JSON.stringify uses ECMAScript string serialization required by RFC 8785.
  return Buffer.from(`{${BODY_FIELDS.map((key) =>
    `${JSON.stringify(key)}:${JSON.stringify(body[key])}`).join(',')}}`, 'utf8');
}

function digest(body) {
  return createHash('sha256').update(canonicalBody(body)).digest();
}

export function signEvent(body, seed) {
  if (identityFromSeed(seed) !== body.author) fail('invalid_identity', 'author does not match seed');
  const hash = digest(body);
  return { ...body, id: hash.toString('hex'), sig: b64url(edSign(null, hash, privateFromSeed(seed))) };
}

export function verifyEvent(event) {
  if (!exactFields(event, EVENT_FIELDS)) fail('invalid_event', 'invalid Event fields');
  const body = Object.fromEntries(BODY_FIELDS.map((key) => [key, event[key]]));
  const hash = digest(body);
  if (event.id !== hash.toString('hex')) fail('invalid_event_id');
  let signature;
  try { signature = fromB64url(event.sig, 64); }
  catch { fail('invalid_signature'); }
  if (!edVerify(null, hash, publicFromIdentity(body.author), signature)) {
    fail('invalid_signature');
  }
  return event;
}

export function verificationReceipt(event, {
  source = 'local-file',
  observedAt = new Date().toISOString(),
  expectedEventId = null,
} = {}) {
  const observedEventId = typeof event?.id === 'string' ? event.id : null;
  const receipt = {
    profile: RECEIPT_PROFILE,
    target_event_id: expectedEventId ?? observedEventId,
    observed_event_id: observedEventId,
    source,
    observed_at: observedAt,
    implementation: { name: 'oac_js.mjs', version: CLIENT_VERSION },
    checks: {
      retrieval: expectedEventId === null ? 'not-tested' :
        (observedEventId === expectedEventId ? 'pass' : 'fail'),
      content_id: 'not-tested',
      signature: 'not-tested',
    },
    status: 'fail',
    errors: [],
  };

  if (!exactFields(event, EVENT_FIELDS)) {
    receipt.errors.push('invalid_event');
    return receipt;
  }

  const body = Object.fromEntries(BODY_FIELDS.map((key) => [key, event[key]]));
  let hash;
  try {
    hash = digest(body);
  } catch (error) {
    receipt.errors.push(error.code ?? 'invalid_event');
    return receipt;
  }

  receipt.checks.content_id = event.id === hash.toString('hex') ? 'pass' : 'fail';
  if (receipt.checks.content_id === 'fail') receipt.errors.push('invalid_event_id');

  try {
    const signature = fromB64url(event.sig, 64);
    receipt.checks.signature = edVerify(null, hash, publicFromIdentity(body.author), signature) ?
      'pass' : 'fail';
  } catch {
    receipt.checks.signature = 'fail';
  }
  if (receipt.checks.signature === 'fail') receipt.errors.push('invalid_signature');

  const retrievalPassed = receipt.checks.retrieval !== 'fail';
  if (!retrievalPassed) receipt.errors.push('unexpected_event_id');
  if (retrievalPassed && receipt.checks.content_id === 'pass' &&
      receipt.checks.signature === 'pass') {
    receipt.status = 'pass';
  }
  return receipt;
}

function nodeUrl(base) {
  const url = new URL(base);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    fail('invalid_node_url', 'provide only a Node origin');
  }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' &&
      ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))) {
    fail('https_required', 'public Nodes must use HTTPS');
  }
  return url.origin;
}

async function request(url, options = {}) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(15000) });
  let value;
  try { value = await response.json(); }
  catch { fail('invalid_response', `HTTP ${response.status} did not return JSON`); }
  if (!response.ok) fail(value?.error ?? 'http_error', value?.detail ?? `HTTP ${response.status}`);
  return { http_status: response.status, value };
}

async function identity(path) {
  const metadata = await stat(path);
  if (process.platform !== 'win32' && (metadata.mode & 0o077)) {
    fail('unsafe_identity_permissions', 'identity file must be mode 0600');
  }
  const parsed = JSON.parse(await readFile(path, 'utf8'));
  if (parsed?.format !== 'oac-ed25519-seed-v1' ||
      typeof parsed.private_seed_hex !== 'string' ||
      !/^[0-9a-f]{64}$/.test(parsed.private_seed_hex)) {
    fail('invalid_identity', 'unsupported identity format');
  }
  const seed = Buffer.from(parsed.private_seed_hex, 'hex');
  const author = identityFromSeed(seed);
  if (parsed.identity !== author) fail('invalid_identity', 'identity mismatch');
  return { seed, author };
}

function option(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (index + 1 >= args.length) fail('invalid_argument', `missing value for ${name}`);
  return args[index + 1];
}

function values(args, name) {
  const result = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === name) {
      if (i + 1 >= args.length) fail('invalid_argument', `missing value for ${name}`);
      result.push(args[i + 1]);
      i += 1;
    }
  }
  return result;
}

function flag(args, name) {
  return args.includes(name);
}

function listenerInterval(value, once) {
  const interval = Number(value);
  if (!Number.isFinite(interval) || interval <= 0 || (!once && interval < 5)) {
    fail('invalid_argument', '--interval must be a finite positive number and at least 5 seconds for continuous listening');
  }
  return interval;
}

export async function loadListenerState(path) {
  let payload;
  try {
    payload = await readFile(path, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return new Set();
    fail('invalid_listener_state', `cannot read listener state: ${error.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(payload);
  } catch {
    fail('invalid_listener_state', 'listener state is not valid JSON');
  }
  if (!exactFields(parsed, ['format', 'seen', 'updated_at']) ||
      parsed.format !== LISTENER_STATE_FORMAT ||
      !Array.isArray(parsed.seen) ||
      !parsed.seen.every((id) => typeof id === 'string' && /^[0-9a-f]{64}$/.test(id)) ||
      new Set(parsed.seen).size !== parsed.seen.length ||
      typeof parsed.updated_at !== 'string') {
    fail('invalid_listener_state', 'unsupported or malformed listener state');
  }
  return new Set(parsed.seen);
}

async function saveListenerState(path, seen) {
  const temporary = `${path}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`;
  const payload = JSON.stringify({
    format: LISTENER_STATE_FORMAT,
    seen: [...seen].sort(),
    updated_at: new Date().toISOString(),
  }, null, 2) + '\n';
  try {
    await writeFile(temporary, payload, { flag: 'wx', mode: 0o600 });
    await rename(temporary, path);
  } catch (error) {
    fail('invalid_listener_state', `cannot write listener state: ${error.message}`);
  } finally {
    await rm(temporary, { force: true });
  }
}

async function scanGlobal(base) {
  const genesis = (await request(`${base}/oac/events/${CANONICAL_GENESIS_ID}`)).value;
  verifyEvent(genesis);
  if (genesis.id !== CANONICAL_GENESIS_ID) {
    fail('genesis_mismatch', 'Node returned a different canonical Genesis Event');
  }

  const events = [];
  const eventIds = new Set();
  const cursors = new Set();
  let cursor = null;
  for (let pageNumber = 0; pageNumber < LISTENER_MAX_PAGES; pageNumber += 1) {
    const url = new URL(`${base}/oac/global`);
    url.searchParams.set('limit', String(LISTENER_PAGE_SIZE));
    if (cursor !== null) url.searchParams.set('cursor', cursor);
    const page = (await request(url)).value;
    if (!Array.isArray(page?.events) ||
        !(page.cursor === null || typeof page.cursor === 'string')) {
      fail('invalid_global_page', 'invalid GLOBAL page');
    }
    for (const event of page.events) {
      verifyEvent(event);
      if (eventIds.has(event.id)) fail('repeated_event_id', 'GLOBAL repeated an Event ID');
      eventIds.add(event.id);
      events.push(event);
    }
    if (page.cursor === null) return events;
    if (cursors.has(page.cursor)) fail('repeated_cursor', 'GLOBAL repeated a cursor');
    cursors.add(page.cursor);
    cursor = page.cursor;
  }
  fail('listener_page_limit', 'GLOBAL exceeded the listener page limit');
}

export async function listenCycle(base, statePath, emit = (value) => {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}) {
  const seen = await loadListenerState(statePath);
  const events = await scanGlobal(base);
  const fresh = events.filter((event) => !seen.has(event.id));
  for (const event of fresh) {
    emit({ kind: 'oac_event', source: base, event });
    seen.add(event.id);
  }
  if (fresh.length > 0) await saveListenerState(statePath, seen);
  return { scanned: events.length, new: fresh.length, known: events.length - fresh.length };
}

async function listen(rest) {
  const base = nodeUrl(rest[0] ?? DEFAULT_NODE);
  const statePath = option(rest, '--state', DEFAULT_LISTENER_STATE);
  const once = flag(rest, '--once');
  const interval = listenerInterval(option(rest, '--interval', String(DEFAULT_LISTENER_INTERVAL)), once);
  while (true) {
    let delay = interval;
    try {
      const stats = await listenCycle(base, statePath);
      process.stderr.write(`${JSON.stringify({
        kind: 'oac_listener_status', source: base, ...stats,
      })}\n`);
    } catch (error) {
      if (once || FATAL_LISTENER_ERRORS.has(error.code)) throw error;
      process.stderr.write(`${JSON.stringify({
        error: error.code ?? 'listener_failed', detail: error.message,
      })}\n`);
      delay = LISTENER_RETRY_INTERVAL;
    }
    if (once) return undefined;
    await new Promise((resolve) => setTimeout(resolve, delay * 1000));
  }
}

async function main(args) {
  const [command, ...rest] = args;
  if (command === 'keygen') {
    const path = option(rest, '--out', 'oac-identity.json');
    const seed = randomBytes(32);
    const author = identityFromSeed(seed);
    await writeFile(path, JSON.stringify({
      format: 'oac-ed25519-seed-v1', identity: author, private_seed_hex: seed.toString('hex'),
    }, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    return { identity: author, file: path };
  }
  if (command === 'sign') {
    const { seed, author } = await identity(option(rest, '--identity', 'oac-identity.json'));
    const event = signEvent({
      v: '0.1',
      type: option(rest, '--type', 'signal'),
      author,
      time: Math.floor(Date.now() / 1000),
      topic: values(rest, '--topic'),
      text: option(rest, '--text', ''),
      refs: values(rest, '--ref'),
    }, seed);
    verifyEvent(event);
    const path = option(rest, '--out', 'event.json');
    await writeFile(path, JSON.stringify(event, null, 2) + '\n', { flag: 'wx', mode: 0o644 });
    return { id: event.id, file: path };
  }
  if (command === 'verify') {
    const event = JSON.parse(await readFile(rest[0] ?? 'event.json', 'utf8'));
    verifyEvent(event);
    return { status: 'verified', id: event.id };
  }
  if (command === 'receipt') {
    const target = rest[0] ?? 'event.json';
    if (/^https?:\/\//.test(target)) {
      const base = nodeUrl(target);
      const id = rest[1];
      if (!/^[0-9a-f]{64}$/.test(id ?? '')) fail('invalid_argument', 'event ID required');
      const event = (await request(`${base}/oac/events/${id}`)).value;
      return verificationReceipt(event, { source: base, expectedEventId: id });
    }
    const event = JSON.parse(await readFile(target, 'utf8'));
    return verificationReceipt(event, {
      source: option(rest, '--source', 'local-file'),
      expectedEventId: option(rest, '--event-id', null),
    });
  }
  if (command === 'discover') {
    const base = nodeUrl(rest[0] ?? DEFAULT_NODE);
    return (await request(`${base}/.well-known/oac.json`)).value;
  }
  if (command === 'list') {
    const base = nodeUrl(rest[0] ?? DEFAULT_NODE);
    const url = new URL(`${base}/oac/global`);
    url.searchParams.set('limit', option(rest, '--limit', '20'));
    const cursor = option(rest, '--cursor', null);
    if (cursor !== null) url.searchParams.set('cursor', cursor);
    const page = (await request(url)).value;
    if (!Array.isArray(page.events)) fail('invalid_response', 'missing events');
    page.events.forEach(verifyEvent);
    return page;
  }
  if (command === 'listen') return listen(rest);
  if (command === 'read') {
    const base = nodeUrl(rest[0] ?? DEFAULT_NODE);
    const id = rest[1];
    if (!/^[0-9a-f]{64}$/.test(id ?? '')) fail('invalid_argument', 'event ID required');
    const event = (await request(`${base}/oac/events/${id}`)).value;
    verifyEvent(event);
    if (event.id !== id) fail('invalid_event_id', 'read returned a different Event');
    return event;
  }
  if (command === 'publish') {
    const base = nodeUrl(rest[0] ?? DEFAULT_NODE);
    const event = JSON.parse(await readFile(rest[1] ?? 'event.json', 'utf8'));
    verifyEvent(event);
    const { http_status, value } = await request(`${base}/oac/events`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
    });
    if (value.id !== event.id || !['accepted', 'known'].includes(value.status)) {
      fail('invalid_response', 'publish response does not match Event');
    }
    const stored = (await request(`${base}/oac/events/${event.id}`)).value;
    verifyEvent(stored);
    if (!EVENT_FIELDS.every((key) => JSON.stringify(stored[key]) === JSON.stringify(event[key]))) {
      fail('invalid_response', 'read-back does not match published Event');
    }
    return { http_status, ...value, read_back: 'verified' };
  }
  fail('invalid_argument', 'commands: discover, list, listen, read, keygen, sign, verify, receipt, publish');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2))
    .then((value) => {
      if (value !== undefined) process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
      if (value?.profile === RECEIPT_PROFILE && value.status !== 'pass') process.exitCode = 2;
    })
    .catch((error) => {
      process.stderr.write(`${JSON.stringify({ error: error.code ?? 'client_error', detail: error.message })}\n`);
      process.exitCode = 1;
    });
}
