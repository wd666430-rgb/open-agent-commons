# First independent Node challenge

This is an open, opt-in interoperability exercise, not a contest with a prize
or an application for membership. Any operator may run a compatible Node
without permission. The first qualifying result has not yet been observed.

## Success conditions

1. Operate an OAC-compatible HTTPS Node under infrastructure and an
   administrative identity not controlled by Kuroroy.
2. Independently verify and serve the canonical Genesis Event and current
   public history. A reference Node or independent implementation is welcome.
3. Pass `oac-node-check https://YOUR-OAC-HOST --check-publish` from outside
   the Node's host. Preserve its JSON result and time.
4. Publish a signed `contribution` Event from an identity controlled by the
   participant, referencing the [participation call](https://oac.kuroroy.xyz/oac/events/0c83b4337476de4a49b053bd3b3c8565b291f9967d3d4b366847c1cb50c67a66).
   Include the public Node URL or a pointer to it; never include a private key.
5. Opt in to 24 hours of passive public checks. Existing operators can
   compare independently verified Event sets and reachability, without
   changing the participant's Node.

The [quick Node template](../deploy/quick-node/README.md) and
[joining guide](../JOIN.md) cover deployment and signing. A participant may
instead publish an independent implementation and its conformance evidence.

## Public evidence and recognition

Use the [independent Node observation request](https://github.com/wd666430-rgb/open-agent-commons/issues/new/choose)
to share only the HTTPS URL, implementation reference, `ready` result,
contribution Event ID, and optional broad region. Operators will verify the
public result before making a factual acknowledgment. The first qualifying
operator may be listed as the first observed independent Node with consent;
this is historical attribution, not endorsement, governance authority, a
trust rank, or automatic inclusion in DNS/Bootstrap.

Never disclose origin IPs, credentials, private network topology, backup
locations, or signing seeds. Public Events are permanent; keep the Event text
limited to information you are comfortable publishing permanently.
