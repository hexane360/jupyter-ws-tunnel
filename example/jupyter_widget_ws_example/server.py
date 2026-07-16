from __future__ import annotations

import logging
import os
import typing as t

import asyncio
from quart import Quart, request, websocket, render_template


app = Quart(__name__)

@app.route("/")
async def index() -> str:
    return await render_template('index.html')

@app.websocket("/ws1")
async def websocket1() -> None:
    await websocket.accept()
    await websocket.send_json({'msg': 'connected'})

    while True:
        await asyncio.sleep(1.0)
        await websocket.send_json({'msg': 'ping'})
        logging.info(f"pong: {await websocket.receive_json()!r}")


async def serve_in_background(
    hostname: str = 'localhost',
    port: t.Optional[int] = None,
    root_path: t.Optional[str] = None,
    serving_cb: t.Optional[t.Callable[[], t.Any]] = None,
    log_handlers: t.Optional[t.Sequence[logging.Handler]] = None,
) -> None:
    """Coroutine that serves `app` via Hypercorn. Named for how it's meant to be
    used from inside an already-running event loop — e.g. a Jupyter kernel cell,
    via `asyncio.ensure_future(serve_in_background(...))` — so it can run
    alongside a comm-attached widget (`comm_bridge.attach_widget`) on the same
    loop. `run` uses it directly for the blocking standalone-CLI case.
    """
    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    host = f"{hostname}:{port or 5050}"
    root_path = root_path or os.environ.get("SCRIPT_NAME")

    if serving_cb:
        app.before_serving(serving_cb)

    logging.basicConfig(level=logging.DEBUG, handlers=log_handlers)

    @app.before_request
    async def log_request() -> None:
        logging.debug(f"{request.method} {request.path} {request.user_agent}")

    logger = logging.getLogger()
    config = Config.from_mapping(
        bind=host,
        root_path=root_path,
        accesslog=logger,
        errorlog=logger,
    )
    await serve(app, config)


def run(
    hostname: str = 'localhost',
    port: t.Optional[int] = None,
    root_path: t.Optional[str] = None,
    serving_cb: t.Optional[t.Callable[[], t.Any]] = None,
) -> None:
    """Blocking entry point for the standalone CLI (`main.py`). Owns its own
    event loop via `asyncio.run` — cannot be called from inside an
    already-running loop (e.g. a Jupyter kernel cell)."""
    asyncio.run(serve_in_background(hostname, port, root_path, serving_cb))