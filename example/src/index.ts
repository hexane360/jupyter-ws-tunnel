import { RenderProps } from "@anywidget/types";

let log_messages: string = "Log:";

function render({ model, el }: RenderProps) {
    let text = document.createElement("div");
    text.className = "ws-log";
    text.innerHTML = log_messages;
    el.appendChild(text);
}

export default { render };