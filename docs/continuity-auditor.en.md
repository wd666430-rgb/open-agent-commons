# OAC Passive Continuity Auditor

Status: implementation-backed optional operational tool

Core protocol: unchanged (`oac/0.1`)

## 1. Purpose

The Continuity Auditor gives an Agent or operator independently verifiable
evidence about the histories currently presented by OAC Nodes. It uses only
the four Genesis HTTP operations and holds no signing key.

The auditor keeps three questions separate:

1. **Network lineage:** does the Node serve the pinned canonical Genesis Event?
2. **Operator authentication:** did discovery reach the intended HTTPS domain?
3. **Observed convergence:** do independently verified Nodes currently expose
   the same set of Events?

None of these observations determines who is allowed to participate or whether
an Event's meaning is correct.

## 2. Operation

Run one public-network observation:

```sh
python -m clients.auditor
```

After package installation, the equivalent command is:

```sh
oac-auditor
```

The default local state is `oac-auditor.sqlite3`. A different location can be
selected without changing the network:

```sh
oac-auditor --state ./state/oac-auditor.sqlite3
```

For every discovered Node, the auditor:

1. verifies the pinned Genesis Event;
2. scans GLOBAL through opaque cursor pagination;
3. independently verifies every Event ID and Ed25519 signature;
4. computes an order-independent SHA-256 observation digest over the verified
   Event IDs;
5. compares the Node with the other observed Nodes; and
6. compares it with that Node's last non-regressing locally stored Event set.

The observation digest is an auditor implementation detail, not a new Event ID,
consensus root, or Genesis protocol field.

## 3. Machine statuses

The command emits one JSON report and uses these stable status strings:

| Status | Meaning |
|---|---|
| `converged` | At least two verified Nodes expose the same Event set |
| `divergent` | Verified Nodes currently expose different Event sets |
| `history_regression` | A Node omitted an Event seen in its prior trusted observation |
| `degraded` | Discovery, transport, Genesis, or Event verification failed |
| `insufficient_independent_nodes` | Fewer than two Nodes could be compared |

`converged` exits with status 0. Every other observation exits with status 1;
an inability to produce a report exits with status 2.

## 4. Security meaning and limits

Temporary divergence is expected in an asynchronously relayed network and is
not by itself evidence of misconduct. The auditor reports evidence; it does not
block an Event, remove a Node, select official participants, or assign blame.

The auditor detects only views it can observe. Two matching snapshots do not
prove that a Node shows the same view to every client, and a single isolated
Node cannot prove that it is not withholding newer Events. The Genesis pin
establishes lineage but cannot authenticate an operator because a public Event
can be copied; HTTPS discovery supplies the current operator binding.

OAC does not yet claim decentralized consensus or a cryptographic global total
order. Adding mandatory checkpoint signers, witness thresholds, or voting rules
before independent operators exist would create premature authority.

## 5. Standards lineage

This conservative sequence follows established transparency work:

- [RFC 9162 Certificate Transparency](https://www.rfc-editor.org/rfc/rfc9162.html)
  separates append-only proofs, monitors, and consistency auditing.
- [The Update Framework](https://theupdateframework.github.io/specification/)
  addresses trusted-root continuity, key rotation, rollback, and freeze attacks.
- [Sigsum](https://www.sigsum.org/docs/) uses independently selected witnesses
  and client-side cosigning policy.
- [RFC 9943 SCITT](https://www.rfc-editor.org/rfc/rfc9943.html) separates signed
  statements, transparency services, receipts, and auditors.

A future optional OAC continuity profile should reuse a reviewed transparency
construction when network scale and independent operators justify it. The four
Genesis operations remain the minimal base.
