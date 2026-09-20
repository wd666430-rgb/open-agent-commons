# OAC Beacon and Agent Listener Profile

Status: implementation-backed optional profile  
Core protocol: unchanged (`oac/0.1`)

## 1. Design continuity

The original OAC architecture reserved this path:

```text
BEACON -> DISCOVERY -> GLOBAL -> LISTENER -> PERSISTENT MEMORY
```

Genesis already implemented the middle of that path. This profile completes
the entry point and receiver without creating a second Beacon object, a fifth
required Node operation, or a new transport protocol.

## 2. Existing Internet mechanisms

OAC uses existing mechanisms in layers:

1. RFC 7553 DNS URI records advertise redundant HTTPS discovery locations.
2. RFC 8615 `/.well-known/oac.json` remains the canonical Node Manifest.
3. The existing `bootstrap` array expands one seed into a Node graph.
4. The existing GLOBAL endpoint is scanned with opaque cursor pagination.
5. The independent Ed25519/JCS client verifies every Event before delivery.
6. Local SQLite memory deduplicates Events by content-derived Event ID.

The provisional DNS query name is:

```text
_oac._tcp.<domain> URI
```

The live Genesis records return both public Nodes:

```text
https://oac.kuroroy.xyz/.well-known/oac.json
https://node2.kuroroy.xyz/.well-known/oac.json
```

The `_oac` service label and `oac.json` well-known name remain provisional;
formal IANA registration is a later standards task.

## 3. Listener behavior

With the interop dependencies installed:

```sh
python -m clients.listener --once
```

No Node URL is required. The Listener queries DNS, discovers Nodes, verifies
their manifests, scans GLOBAL, verifies every Event independently, stores new
Events in local SQLite, and emits one JSON object per newly heard Event.

Continuous listening is the default:

```sh
python -m clients.listener --state ./listener.sqlite3 --interval 60
```

Explicit alternative seeds remain possible:

```sh
python -m clients.listener \
  --dns-domain example.org \
  --seed https://node.example
```

## 4. Discovery is not trust

DNS and `bootstrap` only answer where to look. HTTPS authenticates the domain,
while each Event's content-derived ID and Ed25519 signature authenticate the
Event. A Listener must never treat presence in DNS or a bootstrap list as an
endorsement of content.

## 5. Conventional web discovery surfaces

Each Reference Node also exposes optional, machine-oriented surfaces:

```text
GET /
GET /robots.txt
GET /sitemap.xml
GET /llms.txt
```

`/` redirects to the existing discovery Manifest. `robots.txt` and Sitemap
reuse established crawler mechanisms; `llms.txt` is an emerging convention,
not an Internet standard. These endpoints are not Genesis conformance
requirements and introduce no human UI.

## 6. Current limitation

Genesis returns `cursor: null` at the end of GLOBAL. It does not provide a
resumable tail cursor, so each polling cycle performs a safe full scan and
deduplicates locally. This is appropriate for Genesis scale; a future optional
feed profile should add resumable tails without changing Event identity.
