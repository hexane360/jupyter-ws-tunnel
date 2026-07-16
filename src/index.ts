import type { AnyModel } from "@anywidget/types";

/**
 * Wire protocol shared with the Python side (`comm_bridge.py`). A small
 * JSON-serializable envelope carried over the widget's model-sync comm
 * (`model.send` / `model.on("msg:custom")`). Binary payloads travel in the
 * comm's separate `buffers` side-channel rather than base64'd into the JSON.
 *
 * `id` is a logical-connection identifier included from day one so the format
 * can grow multiplexing later without breaking; v1 only ever has one live
 * connection per widget instance.
 */
export type Envelope =
    | { type: "open"; id: string; path: string; query?: string }
    | { type: "accept"; id: string }
    | { type: "data"; id: string; encoding: "text"; text: string }
    | { type: "data"; id: string; encoding: "binary" }
    | { type: "close"; id: string; code?: number; reason?: string };

const CONNECTING = 0;
const OPEN = 1;
const CLOSING = 2;
const CLOSED = 3;

/**
 * The subset of the browser `WebSocket` surface the example relies on. Both the
 * real `WebSocket` and {@link CommWebSocket} satisfy this, so calling code is
 * identical regardless of which transport {@link createSocket} hands back.
 */
export interface SocketLike {
    readonly readyState: number;
    onopen: ((ev: Event) => void) | null;
    onmessage: ((ev: MessageEvent) => void) | null;
    onclose: ((ev: CloseEvent) => void) | null;
    onerror: ((ev: Event) => void) | null;
    send(data: string | BufferSource | Blob): void;
    close(code?: number, reason?: string): void;
}

function genId(): string {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function isEnvelope(msg: unknown): msg is Envelope {
    return (
        typeof msg === "object" &&
        msg !== null &&
        typeof (msg as { type?: unknown }).type === "string" &&
        typeof (msg as { id?: unknown }).id === "string"
    );
}

function toArrayBuffer(data: BufferSource): ArrayBuffer {
    if (ArrayBuffer.isView(data)) {
        return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
    }
    return data.slice(0);
}

/**
 * A `WebSocket`-shaped adapter backed by a widget's model-sync comm. Used in
 * environments (e.g. hosted Colab) where a real WebSocket cannot be proxied but
 * the widget comm channel is available.
 */
export class CommWebSocket extends EventTarget implements SocketLike {
    static readonly CONNECTING = CONNECTING;
    static readonly OPEN = OPEN;
    static readonly CLOSING = CLOSING;
    static readonly CLOSED = CLOSED;

    readyState: number = CONNECTING;
    onopen: ((ev: Event) => void) | null = null;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    onclose: ((ev: CloseEvent) => void) | null = null;
    onerror: ((ev: Event) => void) | null = null;

    private readonly model: AnyModel;
    private readonly id: string = genId();
    private readonly handler: (msg: unknown, buffers: DataView[]) => void;
    private torn = false;

    constructor(path: string, model: AnyModel) {
        super();
        this.model = model;
        this.handler = (msg, buffers) => this.onCustomMessage(msg, buffers);
        model.on("msg:custom", this.handler);
        // No TCP handshake to observe: the server side signals readiness with an
        // explicit `accept` envelope (see onCustomMessage), mirroring ASGI.
        this.emit({ type: "open", id: this.id, path });
    }

    send(data: string | BufferSource | Blob): void {
        if (this.readyState !== OPEN) {
            throw new DOMException("CommWebSocket is not open", "InvalidStateError");
        }
        if (typeof data === "string") {
            this.emit({ type: "data", id: this.id, encoding: "text", text: data });
        } else if (data instanceof Blob) {
            // Blob -> bytes is inherently async (no sync read API), unlike a real
            // WebSocket where the browser queues the read internally. This can
            // reorder relative to sends made immediately after — acceptable for
            // the uncommon Blob case.
            data.arrayBuffer().then((buffer) =>
                this.emit({ type: "data", id: this.id, encoding: "binary" }, [buffer]),
            );
        } else {
            this.emit({ type: "data", id: this.id, encoding: "binary" }, [toArrayBuffer(data)]);
        }
    }

    close(code = 1000, reason = ""): void {
        if (this.readyState === CLOSING || this.readyState === CLOSED) return;
        this.readyState = CLOSING;
        this.emit({ type: "close", id: this.id, code, reason });
        this.teardown();
        this.readyState = CLOSED;
        this.fire(new CloseEvent("close", { code, reason, wasClean: true }), this.onclose);
    }

    private emit(envelope: Envelope, buffers?: ArrayBuffer[]): void {
        this.model.send(envelope, undefined, buffers);
    }

    private onCustomMessage(msg: unknown, buffers: DataView[]): void {
        if (!isEnvelope(msg) || msg.id !== this.id) return;
        switch (msg.type) {
            case "accept": {
                this.readyState = OPEN;
                this.fire(new Event("open"), this.onopen);
                break;
            }
            case "data": {
                let data: string | ArrayBuffer | SharedArrayBuffer;
                if (msg.encoding === "text") {
                    data = msg.text;
                } else {
                    const view = buffers[0];
                    // Don't assume view.buffer is exactly the payload — respect offset/length.
                    data = view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
                }
                this.fire(new MessageEvent("message", { data }), this.onmessage);
                break;
            }
            case "close": {
                this.teardown();
                this.readyState = CLOSED;
                this.fire(
                    new CloseEvent("close", { code: msg.code, reason: msg.reason, wasClean: true }),
                    this.onclose,
                );
                break;
            }
        }
    }

    private fire<E extends Event>(event: E, handler: ((ev: E) => void) | null): void {
        try {
            handler?.(event);
        } finally {
            this.dispatchEvent(event);
        }
    }

    private teardown(): void {
        if (this.torn) return;
        this.torn = true;
        this.model.off("msg:custom", this.handler);
    }
}

/**
 * Returns a real `WebSocket` when no widget model is present (a plain HTTP
 * page), or a comm-backed {@link CommWebSocket} when a model is supplied (a
 * widget frontend). Calling code is identical for both.
 */
export function createSocket(url: string, model?: AnyModel): SocketLike {
    if (model) {
        return new CommWebSocket(url, model);
    }
    return new WebSocket(url);
}
