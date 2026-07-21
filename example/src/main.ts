import Log from "./Log";
import { createSocket, tunnelFetch, type SocketLike } from "jupyter-ws-tunnel";

const log = new Log(document.getElementById("ws-log"));

const scheme = location.protocol === "https:" ? "wss" : "ws";
const socket = createSocket(`${scheme}://${location.host}/ws1`);

log.wireUp(socket);

tunnelFetch(socket, "/api/echo", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ hello: "world" }),
})
    .then((res) => res.json())
    .then((json) => log.log(`fetch: ${JSON.stringify(json)}`))
    .catch((err) => log.log(`fetch error: ${err}`));
