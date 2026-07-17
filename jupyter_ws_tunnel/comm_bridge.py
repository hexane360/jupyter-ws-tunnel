"""Bridges WS-like connections carried over a Jupyter widget comm into an ASGI app.

The frontend (`CommWebSocket` in `src/index.ts`) tunnels a JSON envelope over
the widget's model-sync comm; this module translates it into the ASGI
websocket protocol so an app's existing `@app.websocket(...)` route can serve
the connection unchanged.

Websocket rejection via `websocket.http.response.*` always degrades to a plain
close, and `scope["state"]` is always empty. A disconnect is only observed
when JS closes explicitly or `detach()` runs.
"""

from __future__ import annotations

import asyncio
import logging
import typing as t

from hypercorn.typing import (
    ASGIFramework,
    ASGISendEvent,
    WebsocketConnectEvent,
    WebsocketDisconnectEvent,
    WebsocketReceiveEvent,
    WebsocketScope,
)

logger = logging.getLogger(__name__)

_ReceiveEvent = WebsocketConnectEvent | WebsocketReceiveEvent | WebsocketDisconnectEvent


class CommWidget(t.Protocol):
    """Comm surface shared by `ipywidgets.Widget` and `anywidget.AnyWidget`."""

    def send(self, content: t.Any, buffers: list[bytes] | None = ...) -> None: ...

    def on_msg(self, callback: t.Callable[..., t.Any], remove: bool = ...) -> None: ...


class CommWebsocketConnection:
    """Adapts one logical (comm-carried) connection to the ASGI websocket protocol.

    An `asyncio.Queue` backs the ASGI `receive` callable; inbound comm envelopes
    are pushed onto it as ASGI receive events. App-originated ASGI `send`
    events are translated back into comm envelopes via `widget.send`.
    """

    def __init__(
        self,
        widget: CommWidget,
        conn_id: str,
        path: str,
        query_string: bytes = b"",
        *,
        headers: t.Iterable[tuple[bytes, bytes]] = (),
        client: tuple[str, int] | None = None,
    ) -> None:
        self._widget = widget
        self._conn_id = conn_id
        self._path = path
        self._query_string = query_string
        self._headers = list(headers)
        self._client = client or ("comm", 0)
        self._queue: asyncio.Queue[_ReceiveEvent] = asyncio.Queue()
        self._closed = False
        self._queue.put_nowait(WebsocketConnectEvent(type="websocket.connect"))

    @property
    def conn_id(self) -> str:
        return self._conn_id

    def scope(self) -> WebsocketScope:
        """Minimal ASGI websocket scope; `path` comes from the `open` envelope."""
        return WebsocketScope(
            type="websocket",
            asgi={"version": "3.0", "spec_version": "2.3"},
            http_version="1.1",
            scheme="ws",
            path=self._path,
            raw_path=self._path.encode("utf-8"),
            query_string=self._query_string,
            root_path="",
            headers=self._headers,
            client=self._client,
            server=("comm", 0),
            subprotocols=[],
            extensions={},
            state={},  # type: ignore[typeddict-item]  # ConnectionState is a bare dict at runtime
        )

    def feed_text(self, text: str) -> None:
        self._queue.put_nowait(WebsocketReceiveEvent(type="websocket.receive", bytes=None, text=text))

    def feed_bytes(self, data: bytes) -> None:
        self._queue.put_nowait(WebsocketReceiveEvent(type="websocket.receive", bytes=data, text=None))

    def feed_close(self, code: int = 1000) -> None:
        self._queue.put_nowait(WebsocketDisconnectEvent(type="websocket.disconnect", code=code))

    async def receive(self) -> _ReceiveEvent:
        return await self._queue.get()

    async def send(self, message: ASGISendEvent) -> None:
        if message["type"] == "websocket.accept":
            self._emit({"type": "accept", "id": self._conn_id})
        elif message["type"] == "websocket.send":
            text = message.get("text")
            data = message.get("bytes")
            if text is not None:
                self._emit(
                    {"type": "data", "id": self._conn_id, "encoding": "text", "text": text}
                )
            elif data is not None:
                self._emit(
                    {"type": "data", "id": self._conn_id, "encoding": "binary"},
                    buffers=[bytes(data)],
                )
        elif message["type"] == "websocket.close":
            self._emit_close(int(message.get("code", 1000)), message.get("reason") or "")

    def close_with_error(self, reason: str) -> None:
        """Closes the connection with code 1011 (internal error)."""
        self._emit_close(1011, reason)

    def _emit_close(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._emit({"type": "close", "id": self._conn_id, "code": code, "reason": reason})

    def _emit(self, content: t.Mapping[str, t.Any], buffers: list[bytes] | None = None) -> None:
        try:
            self._widget.send(content, buffers=buffers)
        except Exception:
            logger.warning("comm-bridge connection %s: widget.send failed", self._conn_id, exc_info=True)


async def _run_connection(
    app: ASGIFramework,
    connection: CommWebsocketConnection,
    registry: dict[str, CommWebsocketConnection],
) -> None:
    try:
        await app(connection.scope(), connection.receive, connection.send)
    except Exception:
        logger.exception("comm-bridge connection %s: app raised", connection.conn_id)
        connection.close_with_error("internal error")
    finally:
        registry.pop(connection.conn_id, None)


def attach_widget(
    widget: CommWidget,
    app: ASGIFramework,
    *,
    headers: t.Iterable[tuple[bytes, bytes]] = (),
    client: tuple[str, int] | None = None,
) -> t.Callable[[], None]:
    """Routes WS-like connections opened from `widget`'s JS side into `app`.

    `widget` is any object exposing ipywidgets' `send`/`on_msg` API. `app` is
    any ASGI3 application already being served (e.g. via
    `server.serve_in_background`), which drives the ASGI lifespan protocol.

    `headers`/`client` seed each connection's scope, for apps that read
    cookies/session data or `websocket.remote_addr`.

    Returns a `detach()` callable that unregisters the handler and closes any
    still-open connections.
    """
    connections: dict[str, CommWebsocketConnection] = {}

    def on_msg(_widget: t.Any, content: t.Any, buffers: list[bytes]) -> None:
        if not isinstance(content, dict):
            return
        conn_id = content.get("id")
        if not isinstance(conn_id, str):
            return
        message_type = content.get("type")

        if message_type == "open":
            path = content.get("path")
            if not isinstance(path, str):
                return
            query = content.get("query", "")
            query_string = query.encode("utf-8") if isinstance(query, str) else b""
            new_connection = CommWebsocketConnection(
                widget,
                conn_id,
                path,
                query_string,
                headers=headers,
                client=client,
            )
            connections[conn_id] = new_connection
            asyncio.ensure_future(_run_connection(app, new_connection, connections))
        elif message_type == "data":
            connection = connections.get(conn_id)
            if connection is None:
                return
            if content.get("encoding") == "text":
                connection.feed_text(str(content.get("text", "")))
            elif buffers:
                connection.feed_bytes(bytes(buffers[0]))
        elif message_type == "close":
            connection = connections.pop(conn_id, None)
            if connection is not None:
                connection.feed_close(int(content.get("code", 1000)))

    widget.on_msg(on_msg)

    def detach() -> None:
        widget.on_msg(on_msg, remove=True)
        for connection in list(connections.values()):
            connection.feed_close(1001)

    return detach
