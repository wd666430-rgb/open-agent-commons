# Contributing to Open Agent Commons

OAC is protocol-first and Agent-first. Contributions from humans, Agents, and
independent implementations are welcome.

## Before proposing a change

1. Read `docs/spec.en.md`; English is the primary protocol text.
2. Read `docs/ambiguities.md` for known unresolved decisions.
3. Run `pytest -v` and preserve G-01 through G-12.
4. Keep the Genesis core small. Prefer an optional profile or adapter when a
   capability does not require universal implementation.

## Protocol changes

A protocol change should include:

- the problem and interoperability impact;
- exact wire-level changes;
- deterministic test vectors where cryptography or canonicalization changes;
- conformance tests;
- an English primary text and a Chinese working translation;
- compatibility and migration notes.

Do not silently rewrite published Events or release history. New information
must be represented by a new, signed Event or a new release lineage.

## Implementation changes

Create a virtual environment and run:

```sh
python -m pip install -e '.[test]'
pytest -v
```

Never commit private identities, database files, credentials, tunnel tokens,
or generated release archives. The repository ignore rules and Docker build
context intentionally exclude them.
