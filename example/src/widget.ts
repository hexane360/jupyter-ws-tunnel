import { RenderProps, InitializeProps } from "@anywidget/types";
import Log from "./Log";
import { createSocket, SocketLike } from "./socket";

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

    // Passing `model` yields a comm-backed socket; the same calls would drive a
    // real WebSocket if `model` were omitted (see main.ts).
    const socket = createSocket("/ws1", model);
    wireUp(socket, log);

    // Tear the socket down when anywidget disposes the view.
    signal.addEventListener("abort", () => socket.close());
}

function wireUp(socket: SocketLike, log: Log) {
    socket.onopen = () => log.log("connected");
    socket.onclose = () => log.log("closed");
    socket.onerror = () => log.log("error");
    socket.onmessage = (event) => {
        const data = typeof event.data === "string" ? event.data : "[binary]";
        log.log(`recv: ${data}`);
        // Reply so the server's receive_json()/ping loop keeps flowing.
        socket.send(JSON.stringify({ msg: "pong" }));
    };
}

export default { initialize, render };
