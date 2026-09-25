import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from ui.nc_tab import NcTab


def main():
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Quality Checklist")
    window.resize(1200, 700)

    tabs = QTabWidget()

    checklist_tab = QWidget()
    nc_tab = NcTab()

    tabs.addTab(checklist_tab, "Quality Checklist")
    tabs.addTab(nc_tab, "Share Non-conformity")

    window.setCentralWidget(tabs)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
