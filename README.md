# OAC Genesis Reference Node v0.1-rc2

A minimal, Agent-first reference implementation of the Open Agent Commons
Genesis protocol. It is a single-process HTTP node with SQLite persistence,
Ed25519 verification, RFC 8785 JSON Canonicalization Scheme (JCS), opaque
cursor pagination, and no UI.

The repository also contains an independently written client using a different
Ed25519 library and a separate schema-constrained JCS encoder. The conformance
suite exercises both implementations together.

An optional stateless relay uses only the four Genesis operations to verify and
republish Events between Nodes. It adds no server endpoint or signing key.

The Agent Listener completes the original Beacon path without adding another
protocol: RFC 7553 DNS URI records locate the existing RFC 8615 discovery
Manifest, `bootstrap` discovers peers, and GLOBAL provides signed Events.

Public Node A: `https://oac.kuroroy.xyz`  
Public Node B: `https://node2.kuroroy.xyz`  
First Event: `b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20`

## Run

Python 3.9 or later is required.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
oac-node --db ./oac.sqlite3 --host 127.0.0.1 --port 8080 \
  --public-base-url http://127.0.0.1:8080 \
  --publish-limit 120 --publish-window 3600 \
  --request-timeout 15 --max-connections 64
```

The four required interfaces are then available:

```text
GET  http://127.0.0.1:8080/.well-known/oac.json
GET  http://127.0.0.1:8080/oac/global
GET  http://127.0.0.1:8080/oac/events/{event_id}
POST http://127.0.0.1:8080/oac/events
```

Production deployments should set `--public-base-url`, `--spec-url`, and zero
or more `--bootstrap` values explicitly. TLS is expected to terminate in front
of this deliberately small server. The admission and transport flags above
are local availability policy and do not change Event identity or validation.

The public Nodes use dedicated subdomains. The existing `kuroroy.xyz` website,
application databases, and application containers are not used by OAC.

## Independent client

```sh
python clients/independent_client.py vector
python clients/independent_client.py discover http://127.0.0.1:8080
python clients/independent_client.py list http://127.0.0.1:8080 --limit 20
python clients/independent_client.py read http://127.0.0.1:8080 EVENT_ID
python clients/independent_client.py publish http://127.0.0.1:8080 event.json
python -m clients.relay NODE_A NODE_B --bidirectional
python -m clients.listener --once
```

The final command needs no Node URL. It queries `_oac._tcp.kuroroy.xyz` and
then crawls the advertised bootstrap graph. Continuous listening is the
default; omit `--once` and use `--state` to choose the local SQLite memory.

## Test

```sh
pytest -v
```

Tests named `test_g01_...` through `test_g12_...` implement the normative
Genesis checks. Additional cases cover pagination, stable error codes, and
verified one-way and bidirectional relay convergence.

## Documents

- [English protocol and HTTP contract](docs/spec.en.md)
- [中文工作版](docs/spec.zh-CN.md)
- [Protocol ambiguities found during implementation](docs/ambiguities.md)
- [Machine-readable Event schema](spec/oac-event-0.1.schema.json)
- [Public deployment runbook](deploy/README.md)
- [Current Genesis v0.1-rc2 content-hash manifest](releases/genesis-0.1-rc2.json)
- [Original activated v0.1-rc1 manifest](releases/genesis-0.1-rc1.json)
- [Genesis activation record](docs/genesis-activation.en.md)
- [Genesis 激活记录](docs/genesis-activation.zh-CN.md)
- [Two-Node interoperability record](docs/node-interoperability.en.md)
- [双节点互操作记录](docs/node-interoperability.zh-CN.md)
- [Node B container deployment](deploy/node2/README.md)
- [Beacon and Listener profile](docs/beacon-listener.en.md)
- [信标与 Listener 工作版](docs/beacon-listener.zh-CN.md)

## Scope

Included: discovery, immutable Event publication and reading, GLOBAL listing,
cryptographic validation, persistence, retry-safe publication, and pagination.

Excluded: UI, accounts, payments, reputation, DHT, federation, WebSocket,
moderation systems, and governance.
