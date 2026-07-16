from pathlib import Path

import anywidget

bundler_output_dir = Path(__file__).parent / "static"

class MyWidget(anywidget.AnyWidget):
    _esm = bundler_output_dir / "index.js"
    _css = bundler_output_dir / "style.css"