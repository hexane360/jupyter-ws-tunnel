import Log from "./Log";
import { createSocket } from "jupyter-widget-ws";

const log = new Log(document.getElementById("ws-log"));

// No model on a plain HTTP page, so createSocket returns a real WebSocket.
const scheme = location.protocol === "https:" ? "wss" : "ws";
const socket = createSocket(`${scheme}://${location.host}/ws1`);

socket.onopen = () => log.log("connected");
socket.onclose = () => log.log("closed");
socket.onerror = () => log.log("error");
socket.onmessage = (event) => {
    const data = typeof event.data === "string" ? event.data : "[binary]";
    log.log(`recv: ${data}`);
    // Reply so the server's receive_json()/ping loop keeps flowing.
    socket.send(JSON.stringify({ msg: "pong" }));
};
