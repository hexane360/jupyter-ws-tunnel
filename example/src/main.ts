import Log from "./Log";
import { createSocket } from "jupyter-ws-tunnel";

const log = new Log(document.getElementById("ws-log"));

const scheme = location.protocol === "https:" ? "wss" : "ws";
const socket = createSocket(`${scheme}://${location.host}/ws1`);

log.wireUp(socket);
