
import sys
import typing as t

import click


@click.command()
@click.option('--host', type=str, default='localhost', help="Host to serve on")
@click.option('--port', type=int, help="Port to serve on")
def main(host: str, port: t.Optional[int]):
    from jupyter_ws_tunnel_example.server import run

    if ':' in host:
        (host, port_from_host) = host.rsplit(':', maxsplit=1)
        try:
            port_from_host = int(port_from_host)
        except ValueError:
            print(f"Invalid host '{host}:{port_from_host}'", file=sys.stderr)
            sys.exit(1)

        port = port or port_from_host

    run(
        hostname=host,
        port=port,
    )


if __name__ == '__main__':
    main()