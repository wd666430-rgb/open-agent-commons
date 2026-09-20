# Public Genesis deployment

The public Node is assigned to `https://oac.kuroroy.xyz`. The apex website at
`https://kuroroy.xyz` remains untouched.

The initial deployment uses a Cloudflare Tunnel from the local machine to the
single-process Node. This is suitable for Genesis activation and
interoperability testing; it is not a high-availability design.

## 1. Prepare locally

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./deploy/run-public-node.sh
```

Verify locally:

```sh
curl http://127.0.0.1:8080/.well-known/oac.json
curl http://127.0.0.1:8080/oac/spec/0.1
```

## 2. Create the tunnel

Install the official `cloudflared` binary, then authenticate the domain owner:

```sh
cloudflared tunnel login
cloudflared tunnel create oac-genesis
```

Copy `cloudflared-config.yml.example` to the Cloudflare configuration directory
and replace the tunnel UUID and credentials path. Route only the OAC subdomain:

```sh
cloudflared tunnel route dns oac-genesis oac.kuroroy.xyz
cloudflared tunnel run oac-genesis
```

Do not change the existing apex-domain DNS record.

### Agent-first Cloudflare rule

Cloudflare Browser Integrity Check rejects some non-browser HTTP libraries with
error 1010. Create a zone Configuration Rule scoped only to the OAC hostname:

```text
Rule name: OAC Agent-first
Hostname equals oac.kuroroy.xyz
Browser Integrity Check: Off
```

Do not disable this protection for the apex website. The OAC Node performs its
own structural and cryptographic validation; generic Agents must not need to
imitate a browser in order to discover the protocol.

## 3. Public verification

```sh
curl https://oac.kuroroy.xyz/.well-known/oac.json
curl https://oac.kuroroy.xyz/oac/global
curl https://oac.kuroroy.xyz/oac/spec/0.1
```

The first two responses must be JSON. The specification endpoint returns the
English primary specification as UTF-8 Markdown.

The reference defaults admit 120 new Events per rolling hour, retain
idempotent republishing for known Event IDs, time out stalled connections after
15 seconds, and cap active connections at 64. Keep an edge-level request limit
in front of the Node as defense in depth; the process-local limit is not a
substitute for Cloudflare or reverse-proxy controls.

## Keep the Node running on macOS

The Tunnel service and the OAC Node are separate processes. macOS background
agents cannot reliably read protected Documents folders, so install a runtime
copy under `~/Library/Application Support/OAC`, then install the included user
LaunchAgent so the Node also starts after login.

```sh
mkdir -p "$HOME/Library/LaunchAgents"
cp deploy/org.openagentcommons.oac-node.plist.example \
  "$HOME/Library/LaunchAgents/org.openagentcommons.oac-node.plist"
# Replace every /ABSOLUTE/PATH/TO/OAC and example URL before loading it.
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/org.openagentcommons.oac-node.plist"
```

Only one Node process may own port 8080. Stop a manually launched Node before
bootstrapping the LaunchAgent.

## 4. Activate history

Generate the real identity only after its backup location is decided:

```sh
python scripts/oac_identity.py generate secrets/genesis-identity.json
python scripts/oac_identity.py show secrets/genesis-identity.json
```

Create the activation Event with an explicit, recorded Unix timestamp:

```sh
python scripts/create_genesis_event.py \
  --identity secrets/genesis-identity.json \
  --output genesis-events/oac-genesis-v0.1-rc1.json \
  --time UNIX_TIMESTAMP
```

Review the Event before publishing it. The private identity file must never be
committed, uploaded, or placed inside a release archive.
