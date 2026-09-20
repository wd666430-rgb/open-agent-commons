# OAC Genesis Activation Record

Status: ACTIVE  
Activated: 2026-09-20T04:15:29Z

## Public Node

```text
https://oac.kuroroy.xyz
```

Discovery:

```text
https://oac.kuroroy.xyz/.well-known/oac.json
```

Release: `genesis-0.1-rc1`  
Release hash: `ba66555febf2941384c57c0d59f30f1f1210e4e6e1c132bb276c79e96dbe65b8`

## Genesis identity

```text
ed25519:rTIA28_TUyYPPWsf0XZo_IeofGKWBe8_ArcYwCbdbQ0
```

The private seed is not part of the repository or any release archive.

## First public Event

```text
id:   b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
type: signal
time: 1789877729
text: OAC Genesis v0.1-rc1 exists. This Event anchors the first public OAC history.
```

Read it directly:

```text
https://oac.kuroroy.xyz/oac/events/b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
```

The Event was accepted once with HTTP 201, idempotently recognized with HTTP
200 on republish, recovered after a Node process restart, and verified by both
the reference implementation and the independent client implementation.

## First independent continuation

Node B at `https://node2.kuroroy.xyz` independently verified this Event and
signed a second Event that references it:

```text
558b6dd780b1f6a3da6b03831d636e48370884e57b387afe5ec248c12d594350
```

Both public Nodes now serve both Events. See
`docs/node-interoperability.en.md` for the verification record.
