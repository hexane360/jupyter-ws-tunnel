import type { AnyModel } from "@anywidget/types";

/**
 * Wire protocol shared with the Python side (`comm_bridge.py`), carried over
 * the widget's model-sync comm. Binary payloads travel in the comm's
 * `buffers` side-channel.
 */
export type Envelope =
    | { type: "open"; id: string; path: string; query?: string }
    | { type: "accept"; id: string }
    | { type: "data"; id: string; encoding: "text"; text: string }
    | { type: "data"; id: string; encoding: "binary" }
    | { type: "close"; id: string; code?: number; reason?: string }
    | { type: "http-request"; id: string; method: string; path: string; query?: string; headers: [string, string][]; body?: string | null }
    | { type: "http-response"; id: string; status: number; headers: [string, string][]; body?: string | null };

const CONNECTING = 0;
const OPEN = 1;
const CLOSING = 2;
const CLOSED = 3;

/** Subset of the `WebSocket` API implemented by both a real `WebSocket` and `CommWebSocket`. */
export interface SocketLike extends EventTarget {
    readonly readyState: number;
    onopen: ((ev: Event) => void) | null;
    onmessage: ((ev: MessageEvent) => void) | null;
    onclose: ((ev: CloseEvent) => void) | null;
    onerror: ((ev: Event) => void) | null;
    send(data: string | BufferSource | Blob): void;
    close(code?: number, reason?: string): void;
}

export function genId(): string {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function isEnvelope(msg: unknown): msg is Envelope {
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

/** `WebSocket`-shaped adapter backed by a widget's model-sync comm. */
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

    readonly model: AnyModel;
    private readonly id: string = genId();
    private readonly handler: (msg: unknown, buffers: DataView[]) => void;
    private torn = false;

    constructor(path: string, model: AnyModel) {
        super();
        this.model = model;
        this.handler = (msg, buffers) => this.onCustomMessage(msg, buffers);
        model.on("msg:custom", this.handler);
        this.emit({ type: "open", id: this.id, path });
    }

    send(data: string | BufferSource | Blob): void {
        if (this.readyState !== OPEN) {
            throw new DOMException("CommWebSocket is not open", "InvalidStateError");
        }
        if (typeof data === "string") {
            this.emit({ type: "data", id: this.id, encoding: "text", text: data });
        } else if (data instanceof Blob) {
            // Async Blob read may reorder relative to synchronous sends made after it.
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
        this.handleClosed(code, reason);
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
                    data = view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
                }
                this.fire(new MessageEvent("message", { data }), this.onmessage);
                break;
            }
            case "close": {
                this.handleClosed(msg.code, msg.reason);
                break;
            }
        }
    }

    private handleClosed(code?: number, reason?: string): void {
        this.teardown();
        this.readyState = CLOSED;
        this.fire(new CloseEvent("close", { code, reason, wasClean: true }), this.onclose);
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

/** Returns a real `WebSocket` if no model is given, or a comm-backed `CommWebSocket` if one is. */
export function createSocket(url: string, model?: AnyModel): CommWebSocket | WebSocket {
    if (model) {
        return new CommWebSocket(url, model);
    }
    return new WebSocket(url);
}

export { tunnelFetch } from "./fetch";
