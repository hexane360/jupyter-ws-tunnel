import { RenderProps, InitializeProps } from "@anywidget/types";
import Log from "./Log";
import { createSocket, tunnelFetch, type SocketLike } from "jupyter-ws-tunnel";

let log: Log | undefined;

function render({ el }: RenderProps) {
    const elem = document.createElement("div");
    elem.id = "ws-log";
    elem.className = "ws-log";
    log!.setElem(elem);
    el.appendChild(elem);
}

function initialize({ model, signal }: InitializeProps) {
    log = new Log();
    const socket = createSocket("/ws1", model);
    log.wireUp(socket);
    signal.addEventListener("abort", () => socket.close());

    // createSocket always returns either a real WebSocket or a CommWebSocket, both
    // of which are EventTarget instances.
    tunnelFetch(socket, "/api/echo", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ hello: "world" }),
    })
        .then((res) => res.json())
        .then((json) => log!.log(`fetch: ${JSON.stringify(json)}`))
        .catch((err) => log!.log(`fetch error: ${err}`));
}

export default { initialize, render };
