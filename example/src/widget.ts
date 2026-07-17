import { RenderProps, InitializeProps } from "@anywidget/types";
import Log from "./Log";
import { createSocket } from "jupyter-ws-tunnel";

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
}

export default { initialize, render };
