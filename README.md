# jupyter-ws-tunnel

A WebSocket-shaped client and an ASGI server bridge that transparently falls
back to a Jupyter widget comm when a real WebSocket can't be proxied (e.g.
hosted Google Colab) — the same client code and the same ASGI app work in
both deployments unchanged.

## Install

```
pip install jupyter-ws-tunnel
npm install jupyter-ws-tunnel
```

## Usage

**JS** — drop-in `WebSocket` replacement:

```ts
import { createSocket } from "jupyter-ws-tunnel";

// pass a widget model to tunnel over its comm; omit it for a real WebSocket
const socket = createSocket("/my-route", model);
socket.onmessage = (event) => console.log(event.data);
```

**Python** — attach an existing ASGI app's websocket route to a widget's comm:

```python
from jupyter_ws_tunnel import attach_widget

attach_widget(widget, app)  # app is any ASGI3 app already being served
```

See [`example/`](example/) for a full working demo (a Quart app served both
ways at once).

## License

MIT
