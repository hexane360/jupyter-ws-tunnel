import asyncio
from pathlib import Path
import logging

import anywidget
import ipywidgets as widgets
from IPython.display import display

from .server import app, serve_in_background
from jupyter_widget_ws import attach_widget

bundler_output_dir = Path(__file__).parent / "static"


class MyWidget(anywidget.AnyWidget):
    _esm = bundler_output_dir / "widget.js"
    _css = bundler_output_dir / "style.css"


class _ServerLogHandler(logging.Handler):
    def __init__(self, output: widgets.Output):
        self.output = output
        super().__init__(logging.INFO)

    def emit(self, record: logging.LogRecord):
        try:
            self.output.append_stdout(self.format(record) + '\n')
        except Exception:
            self.handleError(record)


def run_widget(*, port: int = 5050):
    """Serves `app` over both a real HTTP/WebSocket server and the widget's comm."""
    widget = MyWidget()
    output = widgets.Output()
    asyncio.ensure_future(serve_in_background(
        port=port, log_handlers=[_ServerLogHandler(output)]
    ))
    attach_widget(widget, app)

    display(output, widget)