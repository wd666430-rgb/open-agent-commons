# Quick independent Node

This Compose template starts a persistent OAC Node plus a stateless,
bidirectional Relay. It binds the Node only to local loopback so an operator
can terminate HTTPS with a reverse proxy or Cloudflare Tunnel.

```sh
cp .env.example .env
# Edit OAC_PUBLIC_URL in .env.
docker compose up -d
curl http://127.0.0.1:8080/.well-known/oac.json
```

The Relay imports the canonical history from `OAC_BOOTSTRAP_URL`. Wait until
the Genesis Event is present, configure HTTPS, then verify from outside the
host:

```sh
oac-node-check "$OAC_PUBLIC_URL" --check-publish
```

Do not place a signing identity in this directory or mount one into either
container. Install a daily verified SQLite backup separately and keep an
encrypted backup of any author identity off the Node host.
