import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget


def main():
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Quality Checklist")
    window.resize(1200, 700)

    tabs = QTabWidget()

    checklist_tab = QWidget()
    email_tab = QWidget()

    # Add both widgets to `tabs`, with the labels "Checklist" and "Email".

    # Make `tabs` the main window's central widget.

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()