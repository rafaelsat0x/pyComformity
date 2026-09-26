"""Automated tests; run with `python3 -m unittest discover -s tests -v`."""

import os

# Qt widgets need a platform plugin; offscreen works without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
