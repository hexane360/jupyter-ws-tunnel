

export default class Log {
    messages: string = "Log:\n";
    elem: HTMLDivElement | null = null;

    constructor(elem: HTMLDivElement | null = null) {
        this.setElem(elem);
    }

    setElem(elem: HTMLDivElement | null) {
        this.elem = elem;
        if (this.elem) this.elem.innerHTML = this.messages;
    }

    log(msg: string) {
        this.messages += msg + '\n';
        if (this.elem) this.elem.innerHTML = this.messages;
    }
}