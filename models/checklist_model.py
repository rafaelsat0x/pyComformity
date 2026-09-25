from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class ChecklistModel(QAbstractTableModel):
    """Editable in-memory model for checklist records."""

    COLUMNS = (
        ("id", "ID"),
        ("descricao", "Descrição"),
        ("resultado", "Resultado (N/NC/NA)"),
        (
            "identificacao_nc",
            "Data e Hora de identificação da NC",
        ),
        ("responsaveis", "Responsáveis pela resolução"),
        ("classificacao_nc", "Classificação da NC"),
        ("previsao_resolucao", "Data prevista para resolução"),
        (
            "nova_data_resolucao",
            "Nova data para resolução (NC escalonada)",
        ),
        ("escalonamento_em", "Data e hora do escalonamento"),
        ("conclusao_em", "Data e hora da conclusão da NC"),
        ("status_nc", "Status da NC"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._next_id = 1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        key = self.COLUMNS[index.column()][0]
        value = self._items[index.row()][key]

        if role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.EditRole,
        ):
            return value

        if role == Qt.ItemDataRole.BackgroundRole and key == "id":
            return QColor("#e5e7eb")

        if role == Qt.ItemDataRole.TextAlignmentRole and key in {
            "id",
            "resultado",
            "classificacao_nc",
            "status_nc",
        }:
            return Qt.AlignmentFlag.AlignCenter

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            role != Qt.ItemDataRole.EditRole
            or not index.isValid()
            or self.COLUMNS[index.column()][0] == "id"
        ):
            return False

        key = self.COLUMNS[index.column()][0]
        if self._items[index.row()][key] == value:
            return False

        self._items[index.row()][key] = value
        self.dataChanged.emit(
            index,
            index,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
        )
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.COLUMNS[index.column()][0] != "id":
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.COLUMNS[section][1]
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor("#d1d5db")

        if (
            orientation == Qt.Orientation.Vertical
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return section + 1

        return None

    def add_empty_item(self):
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        item = {key: "" for key, _label in self.COLUMNS}
        item["id"] = self._next_id
        self._items.append(item)
        self._next_id += 1
        self.endInsertRows()
        return row

    def remove_items(self, rows):
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._items[row]
                self.endRemoveRows()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(self.COLUMNS):
            return

        key = self.COLUMNS[column][0]
        reverse = order == Qt.SortOrder.DescendingOrder

        def sort_value(item):
            value = item[key]
            normalized = value.casefold() if isinstance(value, str) else value
            return value == "", normalized

        self.layoutAboutToBeChanged.emit()
        self._items.sort(key=sort_value, reverse=reverse)
        self.layoutChanged.emit()

    def calculate_adherence(self):
        total_items = len(self._items)

        not_applicable = sum(1 for item in self._items if item["resultado"] == "NA")
        conforming_items = sum(1 for item in self._items if item["resultado"] == "N")
        applicable_items = total_items - not_applicable

        if applicable_items == 0:
            return 0.0

        return (conforming_items/applicable_items)*100