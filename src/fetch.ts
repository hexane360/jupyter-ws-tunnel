import type { SocketLike } from "./index";
import { CommWebSocket, genId, isEnvelope } from "./index";

/** Resolves once `socket` reaches `OPEN`; rejects if it closes/errors first. No-op if already open. */
function waitOpen(socket: SocketLike & EventTarget): Promise<void> {
    if (socket.readyState === WebSocket.OPEN) return Promise.resolve();
    if (socket.readyState !== WebSocket.CONNECTING) {
        return Promise.reject(new TypeError("tunnelFetch: socket is not open or connecting"));
    }
    return new Promise((resolve, reject) => {
        const cleanup = () => {
            socket.removeEventListener("open", onOpen);
            socket.removeEventListener("close", onFail);
            socket.removeEventListener("error", onFail);
        };
        const onOpen = () => {
            cleanup();
            resolve();
        };
        const onFail = () => {
            cleanup();
            reject(new TypeError("tunnelFetch: socket closed before it opened"));
        };
        socket.addEventListener("open", onOpen);
        socket.addEventListener("close", onFail);
        socket.addEventListener("error", onFail);
    });
}

/** Bypasses tunneling entirely: derives the HTTP(S) origin from the real socket's own URL and calls the real `fetch()`. */
function fetchOverRealSocket(socket: WebSocket, input: string, init?: RequestInit): Promise<Response> {
    const origin = new URL(socket.url);
    origin.protocol = origin.protocol === "wss:" ? "https:" : "http:";
    return fetch(new URL(input, origin), init);
}

/** Tunnels one HTTP request/response pair over `socket`'s comm as first-class `http-request`/`http-response` envelopes. */
async function commHttpRequest(socket: CommWebSocket, input: string, init?: RequestInit): Promise<Response> {
    const model = socket.model;
    // Resolved against an explicit dummy base rather than `new Request(input, init)`
    // directly: this branch never sends `req` over the network, only normalizes it,
    // so it shouldn't depend on an ambient document location existing or being the
    // right origin (the widget's page origin has no relation to the tunneled app).
    const url = new URL(input, "http://tunnel");
    const req = new Request(url, init);
    const body = req.body ? await req.text() : undefined;
    const id = genId();

    return new Promise<Response>((resolve, reject) => {
        const cleanup = () => {
            model.off("msg:custom", onMessage);
            socket.removeEventListener("close", onTransportFailure);
            socket.removeEventListener("error", onTransportFailure);
        };
        const onMessage = (msg: unknown) => {
            if (!isEnvelope(msg) || msg.id !== id || msg.type !== "http-response") return;
            cleanup();
            resolve(new Response(msg.body ?? null, { status: msg.status, headers: new Headers(msg.headers) }));
        };
        const onTransportFailure = () => {
            cleanup();
            reject(new TypeError("tunnelFetch: tunnel closed before a response arrived"));
        };
        model.on("msg:custom", onMessage);
        socket.addEventListener("close", onTransportFailure);
        socket.addEventListener("error", onTransportFailure);
        model.send({
            type: "http-request",
            id,
            method: req.method,
            path: url.pathname,
            query: url.search ? url.search.slice(1) : undefined,
            headers: [...req.headers],
            body,
        });
    });
}

/**
 * `fetch()`-shaped request over an existing, caller-owned `socket`. Dispatches on the
 * socket's concrete class: a real `WebSocket` means a real network path exists, so this
 * bypasses tunneling and calls the platform's real `fetch()` (full fidelity — streaming,
 * binary, no scope cuts); a `CommWebSocket` means comm-only (e.g. hosted Colab), so the
 * request is tunneled as buffered, text/JSON-only `http-request`/`http-response` envelopes.
 */
export async function tunnelFetch(
    socket: WebSocket | CommWebSocket,
    input: string,
    init?: RequestInit,
): Promise<Response> {
    await waitOpen(socket);
    if (socket instanceof CommWebSocket) return commHttpRequest(socket, input, init);
    return fetchOverRealSocket(socket, input, init);
}
