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
import { readFile, writeFile, stat } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const TYPES = new Set(['signal', 'problem', 'proposal', 'contribution', 'result']);
const BODY_FIELDS = ['author', 'refs', 'text', 'time', 'topic', 'type', 'v'];
const EVENT_FIELDS = [...BODY_FIELDS, 'id', 'sig'];
const PKCS8_PREFIX = Buffer.from('302e020100300506032b657004220420', 'hex');
const SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex');
const DEFAULT_NODE = 'https://oac.kuroroy.xyz';
const MAX_SAFE_TIME = Number.MAX_SAFE_INTEGER;

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
  fail('invalid_argument', 'commands: discover, list, read, keygen, sign, verify, publish');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2))
    .then((value) => process.stdout.write(`${JSON.stringify(value, null, 2)}\n`))
    .catch((error) => {
      process.stderr.write(`${JSON.stringify({ error: error.code ?? 'client_error', detail: error.message })}\n`);
      process.exitCode = 1;
    });
}
