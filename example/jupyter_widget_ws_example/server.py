
import logging
import os
import typing as t

import asyncio
from quart import Quart, request, websocket


app = Quart(__name__)


@app.websocket("/ws1")
async def websocket1():
    await websocket.accept()
    await websocket.send_json({'msg': 'connected'})

    while True:
        await asyncio.sleep(1.0)
        await websocket.send_json({'msg': 'ping'})
        print(f"pong: {await websocket.receive_json()!r}")


def run(
    hostname: str = 'localhost',
    port: t.Optional[int] = None,
    root_path: t.Optional[str] = None,
    serving_cb: t.Optional[t.Callable[[], t.Any]] = None,
):
    host = f"{hostname}:{port or 5050}"
    root_path = root_path or os.environ.get("SCRIPT_NAME")

    if serving_cb:
        app.before_serving(serving_cb)

    logging.basicConfig(level=logging.DEBUG)

    @app.before_request
    async def log_request():
        logging.debug(f"{request.method} {request.path} {request.user_agent}")

    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config.from_mapping(
        bind=host,
        root_path=root_path,
    )
    asyncio.run(serve(app, config))