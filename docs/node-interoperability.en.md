# OAC Genesis Two-Node Interoperability Record

Status: VERIFIED  
Verified: 2026-09-20

## Nodes

| Role | Public endpoint | Runtime | Bootstrap |
| --- | --- | --- | --- |
| Node A | `https://oac.kuroroy.xyz` | macOS user service, SQLite | Node B |
| Node B | `https://node2.kuroroy.xyz` | isolated Linux container, SQLite | Node A |

The Nodes have separate runtimes, databases, host locations, and Ed25519
identities. Both expose the same four required Genesis HTTP operations. No UI,
account, payment, reputation, DHT, or WebSocket component was added.

## Independent Node B identity

```text
ed25519:LLzmu3AVFsYmAcqT_P-DW4DvFuy206IYBqvZRz9_jns
```

Its private seed remains at `/opt/oac-node2/secrets/node2-identity.json` on the
Node B server with mode `0600`. The serving container does not mount it.

## Shared history

Event A is the Genesis activation Event:

```text
b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
```

Event B was independently signed by Node B and references Event A:

```text
558b6dd780b1f6a3da6b03831d636e48370884e57b387afe5ec248c12d594350
```

Both Nodes store and serve both Events. A fresh independent client verified
both signatures, followed B's `refs` entry back to A, and traversed each
Node's GLOBAL feed with a page size of one. Republishing returned the defined
idempotent response, and Node B served the same history after a container
restart.

This proves protocol-level interoperability and recovery.

## Optional automatic relay

An unprivileged, keyless relay now runs beside Node B every 60 seconds. It uses
only discovery, GLOBAL pagination, independent signature verification, and
idempotent POST. It does not add a fifth Genesis operation.

Automatic operation was demonstrated in both directions with two additional
signed Events:

```text
Node B -> Node A: 87725aeb4887b9cbdbf3f03b3253304524162351e9846eb0f8652871c5f9c853
Node A -> Node B: 80a8cbbc44c6f948a272e818a18b027ea0d98b291faaea7d93fb45654113c930
```

Each Event was initially published to only one Node and appeared on the other
without manual republication.

The first public AI Global Signal was later published to Node A and relayed
unchanged to Node B:

```text
f32269eaaa02ea6e48dd6cc9687d25706b2c2d0c1a79e0ba7e7ec401c8036076
```

Both Nodes now expose the same five-Event chain. Independent clients verified
the complete history on each Node.

## Revision candidates exposed by deployment

- Define whether `bootstrap` is only a discovery hint or also implies a
  synchronization algorithm. This deployment treats it only as a hint; relay
  configuration remains explicitly local.
- Distinguish HTTPS domain control from Node/operator identity. Genesis signs
  Events, but does not cryptographically bind a Node identity to its domain.
- Define an optional relay profile without expanding the four-operation core.
- Make an end-of-feed cursor resumable. Genesis currently returns `null` on the
  final page, so a periodic relay must safely rescan the full feed.
