import type { SocketLike } from "jupyter-widget-ws";

export default class Log {
    messages: string = "Log:<br>";
    elem: HTMLElement | null = null;

    constructor(elem: HTMLElement | null = null) {
        this.setElem(elem);
    }

    setElem(elem: HTMLElement | null) {
        this.elem = elem;
        if (this.elem) this.elem.innerHTML = this.messages;
    }

    log(msg: string) {
        this.messages += msg + '<br>';
        if (this.elem) this.elem.innerHTML = this.messages;
    }

    wireUp(socket: SocketLike) {
        socket.onopen = () => this.log("connected");
        socket.onclose = () => this.log("closed");
        socket.onerror = () => this.log("error");
        socket.onmessage = (event) => {
            const data = typeof event.data === "string" ? event.data : "[binary]";
            this.log(`recv: ${data}`);
            socket.send(JSON.stringify({ msg: "pong" })); // keeps the server's ping loop going
        };
    }
}
