# OAC Genesis deployment security

This record describes deployment controls around the Genesis v0.1-rc3
protocol. They are local availability and isolation policy; they do not add an
OAC endpoint or change Event identity, signature verification, or relay rules.

## Current topology

- Node A (`oac.kuroroy.xyz`) is published through a Cloudflare Tunnel. The
  local HTTP listener is not exposed directly to the Internet.
- Node B (`node2.kuroroy.xyz`) runs as a non-root, read-only-root-filesystem
  container on the existing server.
- Node B and its stateless relay use the dedicated `oac_public_backend` Docker
  network. Website application and database containers are not members.
- Only the reverse proxy is connected to both the website network and the OAC
  network. The Node publishes no host port other than its loopback binding.
- The serving containers do not receive either Node's signing identity.

## Edge controls

Cloudflare applies a rate limit only to:

```text
Hostname in {oac.kuroroy.xyz, node2.kuroroy.xyz}
AND method = POST
AND path = /oac/events
```

The current edge policy allows 20 requests from one IP address in 10 seconds
and blocks excess requests for 10 seconds. Discovery, GLOBAL listening, and
Event reads are not included in this rule.

The Node independently limits admission to 120 new Events per rolling hour.
Known, valid Event IDs remain idempotent. These limits protect availability;
cryptographic and structural validation remains mandatory for every Event.

Node B's HTTPS virtual host accepts requests only from Cloudflare's published
IPv4 and IPv6 networks and otherwise returns `403 Forbidden`. The allowlist is
kept in a separate reverse-proxy include and must be refreshed only from:

```text
https://www.cloudflare.com/ips-v4
https://www.cloudflare.com/ips-v6
```

Every Node response publishes `Strict-Transport-Security: max-age=31536000`.
The policy is deliberately emitted by the OAC application without
`includeSubDomains`, keeping it scoped to each OAC hostname instead of changing
unrelated services under the parent domain. Plain HTTP is redirected to HTTPS
at the Cloudflare edge.

## Verification on 2026-09-20

- All 29 available local tests passed, including normative G-01 through G-12;
  the optional MCP SDK test is exercised by the Python 3.12 CI job.
- Both public discovery and GLOBAL interfaces returned JSON with HTTP 200.
- Both public Nodes contained the same five verified Events, including the
  signed AI Global Signal.
- Both public Manifests advertised `genesis-0.1-rc3`, and both HTTPS responses
  included the Node-scoped HSTS policy.
- A 36-request invalid-publication burst produced 22 validation responses
  (`422`) followed by 14 edge-limit responses (`429`). No Event was stored.
- Node B remained readable through Cloudflare, while a direct TLS request to
  its origin address returned `403`.
- The DNS URI beacon advertised both public Nodes.

## Remaining operational boundaries

The current deployment is suitable for Genesis interoperability, not high
availability. Node A still depends on one local machine and its Tunnel. Node B
shares a physical server and reverse-proxy process with the website even though
its network, process, filesystem, database, and identity are separated.

Back up each SQLite database and signing identity separately. Never place a
private identity in a container image, repository, log, release archive, or
serving container. Monitor `429`, `403`, process restarts, disk use, and relay
verification failures. Review Cloudflare address-range announcements before
updating the origin allowlist.
