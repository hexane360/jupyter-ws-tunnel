"""Bridge WS-like connections carried over a Jupyter widget comm into an ASGI app.

In deployments where a raw WebSocket can't be proxied (e.g. hosted Colab), the
frontend opens a `CommWebSocket` (see ``src/index.ts``) that tunnels a small
JSON envelope over the widget's model-sync comm. This module translates that
envelope into the ASGI websocket protocol so the *same* unmodified ASGI app that
serves real WebSockets over HTTP (``server.py``'s ``@app.websocket(...)`` routes)
can service the connection unchanged.

Typed against ``hypercorn.typing`` (Quart's own ASGI type source) rather than a
hand-rolled approximation, so an app like Quart's is accepted without a cast.

``attach_widget(widget, app)`` is the comm-mode counterpart to ``server.run``.

Known behavioral gaps versus a real Hypercorn-served connection (the fake scope
has no real headers/client and there's no real ASGI server in front of ``app``):

- An app that rejects a websocket with a real HTTP status via the ASGI
  ``websocket.http.response.*`` events (instead of just closing) will instead
  always degrade to a plain ``websocket.close(1000)`` here — real Hypercorn
  advertises the ``websocket.http.response`` scope extension, our fake scope
  doesn't, and frameworks like Quart gate that feature behind it.
- ``scope["state"]`` is always empty. Real Hypercorn copies ASGI lifespan
  startup state into each connection's scope; an app reading
  ``websocket.scope["state"][...]`` directly (not through Quart's own request
  context, which this bridge doesn't otherwise affect) will find it empty here.
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
        # ASGI contract: the first event an app receives is websocket.connect.
        self._queue.put_nowait(WebsocketConnectEvent(type="websocket.connect"))

    @property
    def conn_id(self) -> str:
        return self._conn_id

    def scope(self) -> WebsocketScope:
        """A minimal ASGI websocket scope. ``path`` comes from the ``open``
        envelope so the same app's route table dispatches as it would for a real
        WebSocket at that path. ``headers``/``client`` are empty/synthetic
        unless explicitly supplied to `attach_widget` — see module docstring for
        what that means for apps relying on cookies/session or remote_addr."""
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
            self._emit_close(int(message.get("code", 1000)), message.get("reason") or "")

    def close_with_error(self, reason: str) -> None:
        """Called by `_run_connection` when the app raises, so the JS side
        actually observes a close instead of hanging with `readyState` stuck
        at OPEN forever."""
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
            # The underlying comm may already be gone (widget disposed, kernel
            # restarting mid-flight) — don't let that surface as a confusing
            # exception from inside the app's own ASGI send() call.
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
    """Route WS-like connections opened from ``widget``'s JS side into ``app``.

    ``widget`` is any object exposing ipywidgets' ``send``/``on_msg`` comm API
    (both ``ipywidgets.Widget`` and ``anywidget.AnyWidget`` qualify). ``app`` is
    any ASGI3 application. Assumes ``app`` is already being served for real
    (e.g. via ``server.serve_in_background``), which is what drives the ASGI
    lifespan protocol — this function only handles the websocket scope.

    ``headers``/``client`` seed every connection's fake scope — supply these if
    ``app`` reads cookies/session data or `websocket.remote_addr`, neither of
    which have a real value over a comm (see module docstring). Left empty by
    default, matching prior behavior.

    Deliberately unbounded message size: this bridge targets *any* ASGI app, not
    specifically Hypercorn, so it doesn't impose Hypercorn's own default limit —
    an app that wants one should enforce it itself.

    Returns a ``detach()`` callable that unregisters the message handler and
    tears down any still-open connections.

    Known v1 limitation: there is no portable signal for the JS side going away
    (tab closed, kernel restart), so a ``websocket.disconnect`` is only delivered
    when JS explicitly closes or `detach()` is called. Long-lived per-connection
    tasks (e.g. an infinite server-side loop) otherwise linger until the kernel
    process exits.
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
        # Unwind any connections still open when the widget is torn down,
        # rather than leaving their app-side tasks running with no owner.
        for connection in list(connections.values()):
            connection.feed_close(1001)  # "going away"

    return detach
