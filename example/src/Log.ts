

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
}