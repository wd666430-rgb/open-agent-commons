# Genesis v0.1 ambiguities found during implementation

This document separates decisions needed for deterministic code from claims
already present in the earlier working draft. The following points should be
accepted or revised before the protocol is declared final.

## Decisions made by the reference profile

1. **Exact field set.** The draft listed required fields but did not say whether
   unknown fields are allowed or signed. This profile rejects them. Otherwise,
   implementations may disagree about whether an extension participates in the
   Event ID and signature.
2. **Event type casing.** Earlier conceptual text used uppercase type names,
   while HTTP vectors used lowercase. The wire values are lowercase.
3. **Signature input.** The signature covers the raw 32-byte SHA-256 digest,
   not its 64-character hexadecimal representation and not the JCS bytes.
4. **Encoding.** Public keys and signatures use RFC 4648 base64url without
   `=` padding. Event IDs use lowercase hexadecimal.
5. **Time.** `time` is a non-negative integer Unix timestamp. No clock-skew or
   freshness policy is applied by protocol validation.
6. **Reference availability.** A Node accepts a valid Event even when a member
   of `refs` is not locally available. Requiring existence would prevent
   out-of-order exchange between Nodes.
7. **GLOBAL ordering.** Pages use stable local acceptance order, not Event
   time. The cursor is Node-local and opaque. A client should expect at-least-
   once page retrieval across retries and deduplicate by Event ID.
8. **Schema failures.** The original error vocabulary had no general code for
   wrong types, unknown fields, malformed author keys, or invalid Event types.
   This profile adds stable `invalid_event`.
9. **Query failures.** This profile adds `invalid_cursor` and `invalid_query`.
10. **Limits.** The reference Node uses a 1 MiB request limit, default page size
    100, and maximum page size 500. These are Node policy, not Event identity.
11. **JCS input domain.** Duplicate JSON object names, non-finite numbers, and
    lone Unicode surrogates are rejected. Integers are limited to the exact
    interoperable range 0 through 2^53-1.
12. **Operational admission policy.** A reference Node admits at most 120 new
    Events per rolling hour by default. Known Event IDs remain idempotently
    publishable without consuming the limit. `429 rate_limited` includes
    `Retry-After`. Operators may change or disable this local policy; it is not
    part of Event identity or cross-Node validation.
13. **Transport hardening.** The reference server applies a 15-second socket
    timeout and a 64-connection process-local ceiling by default. A saturated
    Node returns `503 server_busy` when possible. These are local availability
    controls, not protocol consensus rules.

## Still open for a later revision

- Whether Genesis final should permit a namespaced extension object rather
  than requiring a new protocol version for every new field.
- Whether `topic` strings need normalization, case rules, uniqueness, or size
  limits. This implementation preserves them exactly.
- Whether duplicate values in `topic` or `refs` are valid. This implementation
  preserves them exactly.
- Whether the discovery `spec` value must be an HTTPS URL, may be a content
  address, or may be another URI.
- Whether a public Node must publish cache semantics or snapshot guarantees for
  GLOBAL while concurrent writes occur.
- Whether conformance G-12 requires three separately authored codebases or
  three independent roles/processes across at least two codebases. This suite
  uses a reference Node plus an independently written client for roles B and C.
- A standard error envelope for HTTP methods and operational server failures.

None of these open points requires payments, reputation, DHT, WebSocket, UI, or
other non-Genesis features.
