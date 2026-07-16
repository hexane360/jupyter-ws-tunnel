"""Bridge WS-like connections carried over a Jupyter widget comm into an ASGI app.

In deployments where a raw WebSocket can't be proxied (e.g. hosted Colab), the
frontend opens a `CommWebSocket` (see ``src/socket.ts``) that tunnels a small
JSON envelope over the widget's model-sync comm. This module translates that
envelope into the ASGI websocket protocol so the *same* unmodified ASGI app that
serves real WebSockets over HTTP (``server.py``'s ``@app.websocket(...)`` routes)
can service the connection unchanged.

Typed against ``hypercorn.typing`` (Quart's own ASGI type source) rather than a
hand-rolled approximation, so an app like Quart's is accepted without a cast.

``attach_widget(widget, app)`` is the comm-mode counterpart to ``server.run``.
"""

from __future__ import annotations

import asyncio
import typing as t

from hypercorn.typing import (
    ASGIFramework,
    ASGISendEvent,
    WebsocketConnectEvent,
    WebsocketDisconnectEvent,
    WebsocketReceiveEvent,
    WebsocketScope,
)

ASGIApp = ASGIFramework
# The events CommWebsocketConnection ever pushes through receive().
_ReceiveEvent = WebsocketConnectEvent | WebsocketReceiveEvent | WebsocketDisconnectEvent


class CommWidget(t.Protocol):
    """The comm surface shared by ``ipywidgets.Widget`` and ``anywidget.AnyWidget``.

    Duck-typed so the bridge stays independent of which widget library created
    the model.
    """

    def send(self, content: t.Any, buffers: list[bytes] | None = ...) -> None: ...

    def on_msg(self, callback: t.Callable[..., t.Any], remove: bool = ...) -> None: ...


class CommWebsocketConnection:
    """Adapts one logical (comm-carried) connection to the ASGI websocket protocol.

    An :class:`asyncio.Queue` backs the ASGI ``receive`` callable; inbound comm
    envelopes are pushed onto it as ASGI receive events. App-originated ASGI
    ``send`` events are translated back into comm envelopes via ``widget.send``.
    """

    def __init__(
        self,
        widget: CommWidget,
        conn_id: str,
        path: str,
        query_string: bytes = b"",
    ) -> None:
        self._widget = widget
        self._conn_id = conn_id
        self._path = path
        self._query_string = query_string
        self._queue: asyncio.Queue[_ReceiveEvent] = asyncio.Queue()
        # ASGI contract: the first event an app receives is websocket.connect.
        self._queue.put_nowait(WebsocketConnectEvent(type="websocket.connect"))

    @property
    def conn_id(self) -> str:
        return self._conn_id

    def scope(self) -> WebsocketScope:
        """A minimal ASGI websocket scope. ``path`` comes from the ``open``
        envelope so the same app's route table dispatches as it would for a real
        WebSocket at that path."""
        return WebsocketScope(
            type="websocket",
            asgi={"version": "3.0", "spec_version": "2.3"},
            http_version="1.1",
            scheme="ws",
            path=self._path,
            raw_path=self._path.encode("utf-8"),
            query_string=self._query_string,
            root_path="",
            headers=[],
            client=("comm", 0),
            server=("comm", 0),
            subprotocols=[],
            extensions={},
            state={},  # type: ignore[typeddict-item]  # ConnectionState is a bare dict at runtime
        )

    # -- inbound: comm envelope -> ASGI receive queue --

    def feed_text(self, text: str) -> None:
        self._queue.put_nowait(WebsocketReceiveEvent(type="websocket.receive", bytes=None, text=text))

    def feed_bytes(self, data: bytes) -> None:
        self._queue.put_nowait(WebsocketReceiveEvent(type="websocket.receive", bytes=data, text=None))

    def feed_close(self, code: int = 1000) -> None:
        self._queue.put_nowait(WebsocketDisconnectEvent(type="websocket.disconnect", code=code))

    # -- ASGI callables passed into ``await app(scope, receive, send)`` --

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
            self._emit(
                {
                    "type": "close",
                    "id": self._conn_id,
                    "code": int(message.get("code", 1000)),
                    "reason": message.get("reason") or "",
                }
            )

    def _emit(self, content: t.Mapping[str, t.Any], buffers: list[bytes] | None = None) -> None:
        self._widget.send(content, buffers=buffers)


async def _run_connection(
    app: ASGIApp,
    connection: CommWebsocketConnection,
    registry: dict[str, CommWebsocketConnection],
) -> None:
    try:
        await app(connection.scope(), connection.receive, connection.send)
    finally:
        registry.pop(connection.conn_id, None)


def attach_widget(
    widget: CommWidget,
    app: ASGIApp,
) -> t.Callable[[], None]:
    """Route WS-like connections opened from ``widget``'s JS side into ``app``.

    ``widget`` is any object exposing ipywidgets' ``send``/``on_msg`` comm API
    (both ``ipywidgets.Widget`` and ``anywidget.AnyWidget`` qualify). ``app`` is
    any ASGI3 application. Assumes ``app`` is already being served for real
    (e.g. via ``server.serve_in_background``), which is what drives the ASGI
    lifespan protocol — this function only handles the websocket scope.

    Returns a ``detach()`` callable that unregisters the message handler.

    Known v1 limitation: there is no portable signal for the JS side going away
    (tab closed, kernel restart), so a ``websocket.disconnect`` is only delivered
    when JS explicitly closes. Long-lived per-connection tasks (e.g. an infinite
    server-side loop) linger until the kernel process exits.
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
            new_connection = CommWebsocketConnection(widget, conn_id, path, query_string)
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

    return detach
