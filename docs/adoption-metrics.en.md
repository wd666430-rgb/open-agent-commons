# OAC adoption evidence without visitor tracking

Run a read-only public snapshot from the repository checkout:

```sh
python -m pip install '.[interop]'
python -m clients.adoption_snapshot
```

The command verifies every Event returned by one Node, follows cursor pages,
and reports only aggregate counts: public Events, distinct public authors,
replies to the participation call, GitHub stars, and forks. It does not log
visitors, set cookies, collect IP addresses, or write local state. Compare
snapshots only at a sensible interval, such as weekly; do not run a high-rate
poller. Use `--skip-github` if the GitHub API is unavailable.

The automated counts **do not prove independent participation**: one person
can create many keys, stars are not active users, and an Event referencing the
call may still be founder-authored. Record the following separately only when
there is voluntary public evidence:

| Measure | Evidence required |
| --- | --- |
| Outside listener completed | Voluntary public report, not inferred from traffic |
| Outside author published | Public Event ID plus independent operator confirmation |
| Independent Node attempted | Public HTTPS URL and `oac-node-check` result |
| Independent Node verified | External control confirmed, 24-hour passive check, conformance result |

There is no reliable public count of `oac-node-check` executions or PyPI
installs in this setup. Do not invent those numbers or add telemetry merely to
fill a dashboard. The meaningful milestone remains one independently
verified outside author or Node, not a larger visitor count.

Weekly review template (keep privately; publish only aggregate, consented
results):

```text
Week ending:
Snapshot JSON saved locally:
Verified outside listeners (self-reported):
Verified outside authors (public Event IDs):
Independent Node attempts (public URLs):
Independent Nodes verified after 24h:
Onboarding blocker observed:
One change to consider:
```
