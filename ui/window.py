import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from ui.checklist_tab import ChecklistTab
from ui.nc_tab import NcTab


def main():
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Quality Checklist")
    window.resize(1200, 700)

    tabs = QTabWidget()

    checklist_tab = ChecklistTab()
    nc_tab = NcTab()

    tabs.addTab(checklist_tab, "Quality Checklist")
    tabs.addTab(nc_tab, "Share Non-conformity")

    window.setCentralWidget(tabs)

    # Opens maximized; resize() above is the size used when restoring.
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
