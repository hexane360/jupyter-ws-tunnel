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

@app.route("/api/echo", methods=["POST"])
async def echo() -> dict:
    return {"echo": await request.get_json()}

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
    """Serves `app` via Hypercorn on the current event loop."""
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
    """Blocking entry point for the standalone CLI. Cannot be called from an
    already-running event loop."""
    asyncio.run(serve_in_background(hostname, port, root_path, serving_cb))