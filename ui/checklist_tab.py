from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from models.checklist_model import ChecklistModel


class ChoiceDelegate(QStyledItemDelegate):
    """Dropdown editor used by columns with a fixed set of values."""

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self._choices = choices

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(self._choices)
        return editor

    def setEditorData(self, editor, index):
        value = str(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.setCurrentText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class DateDelegate(QStyledItemDelegate):
    """Calendar editor that displays local dates but stores ISO dates."""

    _EMPTY_DATE = QDate(1900, 1, 1)

    def createEditor(self, parent, option, index):
        editor = QDateEdit(parent)
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd/MM/yyyy")
        editor.setMinimumDate(self._EMPTY_DATE)
        editor.setSpecialValueText("")
        return editor

    def displayText(self, value, locale):
        date = QDate.fromString(str(value or ""), Qt.DateFormat.ISODate)
        return date.toString("dd/MM/yyyy") if date.isValid() else ""

    def setEditorData(self, editor, index):
        value = str(index.data(Qt.ItemDataRole.EditRole) or "")
        date = QDate.fromString(value, Qt.DateFormat.ISODate)
        editor.setDate(date if date.isValid() else self._EMPTY_DATE)

    def setModelData(self, editor, model, index):
        date = editor.date()
        value = (
            ""
            if date == self._EMPTY_DATE
            else date.toString(Qt.DateFormat.ISODate)
        )
        model.setData(index, value, Qt.ItemDataRole.EditRole)


class DateTimeDelegate(QStyledItemDelegate):
    """Calendar editor that displays local date-times but stores ISO values."""

    _EMPTY_DATETIME = QDateTime(QDate(1900, 1, 1), QTime(0, 0))

    def createEditor(self, parent, option, index):
        editor = QDateTimeEdit(parent)
        editor.setCalendarPopup(True)
        editor.setDisplayFormat("dd/MM/yyyy HH:mm")
        editor.setMinimumDateTime(self._EMPTY_DATETIME)
        editor.setSpecialValueText("")
        return editor

    def displayText(self, value, locale):
        date_time = QDateTime.fromString(
            str(value or ""),
            Qt.DateFormat.ISODate,
        )
        return (
            date_time.toString("dd/MM/yyyy HH:mm")
            if date_time.isValid()
            else ""
        )

    def setEditorData(self, editor, index):
        value = str(index.data(Qt.ItemDataRole.EditRole) or "")
        date_time = QDateTime.fromString(value, Qt.DateFormat.ISODate)
        editor.setDateTime(
            date_time if date_time.isValid() else self._EMPTY_DATETIME
        )

    def setModelData(self, editor, model, index):
        date_time = editor.dateTime()
        value = (
            ""
            if date_time == self._EMPTY_DATETIME
            else date_time.toString(Qt.DateFormat.ISODate)
        )
        model.setData(index, value, Qt.ItemDataRole.EditRole)


class ChecklistTab(QWidget):
    """Container for the quality-checklist table and related controls."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = ChecklistModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.horizontalHeader().setStyleSheet(
            "QHeaderView::section {"
            "background-color: #d1d5db;"
            "color: #111827;"
            "font-weight: 600;"
            "padding: 6px;"
            "border: 1px solid #9ca3af;"
            "}"
        )

        self.table.setItemDelegateForColumn(
            2,
            ChoiceDelegate(["", "N", "NC", "NA"], self.table),
        )
        self.table.setItemDelegateForColumn(
            5,
            ChoiceDelegate(
                ["", "Baixa", "Média", "Alta", "Crítica"],
                self.table,
            ),
        )
        self.table.setItemDelegateForColumn(
            10,
            ChoiceDelegate(
                ["", "Aberta", "Em andamento", "Resolvida", "Escalonada"],
                self.table,
            ),
        )

        date_delegate = DateDelegate(self.table)
        for column in (6, 7):
            self.table.setItemDelegateForColumn(column, date_delegate)

        date_time_delegate = DateTimeDelegate(self.table)
        for column in (3, 8, 9):
            self.table.setItemDelegateForColumn(column, date_time_delegate)

        self._set_initial_column_widths()

        add_button = QPushButton("Adicionar item")
        add_button.clicked.connect(self._add_item)

        delete_button = QPushButton("Excluir selecionado")
        delete_button.clicked.connect(self._delete_selected_items)

        button_layout = QHBoxLayout()
        button_layout.addWidget(add_button)
        button_layout.addWidget(delete_button)
        button_layout.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(button_layout)
        layout.addWidget(self.table)

        self._add_item()

    def _set_initial_column_widths(self):
        widths = (60, 280, 150, 220, 220, 160, 190, 240, 210, 220, 170)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    def _add_item(self):
        row = self.model.add_empty_item()
        index = self.model.index(row, 1)
        self.table.scrollTo(index)
        self.table.setCurrentIndex(index)

    def _delete_selected_items(self):
        rows = [
            index.row()
            for index in self.table.selectionModel().selectedRows()
        ]
        if not rows:
            QMessageBox.information(
                self,
                "Excluir item",
                "Selecione pelo menos uma linha para excluir.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Excluir item",
            "Deseja excluir as linhas selecionadas?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.model.remove_items(rows)
