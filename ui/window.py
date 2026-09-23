import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from ui.checklist_tab import ChecklistTab


def main():
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Quality Checklist")
    window.resize(1200, 700)

    tabs = QTabWidget()

    checklist_tab = ChecklistTab()
    email_tab = QWidget()

    tabs.addTab(checklist_tab, "Quality Checklist")
    tabs.addTab(email_tab, "Share Non-conformity")

    window.setCentralWidget(tabs)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
