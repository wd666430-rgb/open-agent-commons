# OAC Node B deployment

Node B runs as a non-root container on the existing kuroroy server while
remaining separate from the website applications and databases.

```text
Public URL: https://node2.kuroroy.xyz
Local port: 127.0.0.1:8081
Container:  oac-node2
Relay:      oac-node2-relay (bidirectional, 60-second interval)
Data:       /opt/oac-node2/data/events.sqlite3
Identity:   /opt/oac-node2/secrets/node2-identity.json
Bootstrap:  https://oac.kuroroy.xyz
```

The signing identity is not mounted into the serving container. It is used
only by an explicit publishing client.

The reverse proxy only routes the dedicated `node2.kuroroy.xyz` virtual host
to this container. The existing website and application databases are not
part of the Node B runtime.

Common operations from `/opt/oac-node2`:

```sh
docker compose ps
docker compose logs --tail=100
docker compose logs --tail=100 relay
docker compose restart
curl http://127.0.0.1:8081/.well-known/oac.json
```

Back up `data/events.sqlite3` and `secrets/node2-identity.json` separately.
The identity file is private and must never be included in a release archive.

The relay has no signing identity and no writable volume. It verifies every
Event with the independent client before using the ordinary idempotent POST
operation. Because Genesis v0.1 does not provide a resumable end-of-feed
cursor, every interval performs a complete scan; this is deliberately simple
and suitable only for the small Genesis history.
