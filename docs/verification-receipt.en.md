# Optional verification receipt

An OAC verification receipt is a machine-readable record of checks performed
on one Event. It is an application-level profile, not a fifth Genesis
operation, a new Event type, or proof that the Event's claims are true.

The dependency-free Node.js client can generate a receipt directly from a
public Node:

```sh
node clients/oac_js.mjs receipt https://oac.kuroroy.xyz EVENT_ID
```

It can also check an offline copy without publishing it:

```sh
node clients/oac_js.mjs receipt event.json --source offline-copy
```

The output records:

- the target and observed Event IDs;
- the source and observation time;
- the client implementation and version;
- separate retrieval, content-ID, and Ed25519-signature outcomes; and
- an overall `pass` or `fail` status.

`not-tested` is explicit: an offline copy has no remote retrieval check, and a
malformed Event may prevent later cryptographic checks from being attempted.
A failed receipt exits with status 2 after printing the JSON evidence.

To make the receipt publicly attributable, an authorised author may place the
receipt JSON or a concise summary in the `text` of a signed `result` Event and
put the verified Event ID in `refs`. No private key belongs in a receipt. A
signed receipt proves only that its author signed the statement; another
observer should repeat the checks rather than trust the statement blindly.

For an interoperability test, two independently operated environments should
check the same authentic Event from different Nodes and compare receipts. An
offline tampered copy can be used as a negative control, but it must never be
published as an authentic Event.
