from __future__ import annotations

import argparse

from .app import NodeConfig, create_server


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="OAC Genesis Reference Node v0.1")
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", default=8080, type=int)
    value.add_argument("--db", default="oac.sqlite3")
    value.add_argument("--public-base-url")
    value.add_argument("--spec-url", default="urn:oac:spec:genesis:0.1")
    value.add_argument("--spec-file")
    value.add_argument("--release", default="genesis-0.1-rc1")
    value.add_argument("--bootstrap", action="append", default=[])
    return value


def main() -> None:
    args = parser().parse_args()
    config = NodeConfig(
        database=args.db,
        public_base_url=args.public_base_url,
        spec_url=args.spec_url,
        spec_path=args.spec_file,
        release=args.release,
        bootstrap=args.bootstrap,
    )
    server = create_server(args.host, args.port, config)
    host, port = server.server_address[:2]
    print(f"OAC Genesis node listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
