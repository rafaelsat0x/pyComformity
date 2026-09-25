import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

# Classification -> days the responsible person has to resolve the NC.
CLASSIFICACOES = {
    "Baixa": 7,
    "Média-Simples": 3,
    "Média-Complexa": 5,
    "Alta": 2,
    "Crítica": 1,
}

STATUS_ABERTA = "Aberta"
STATUS_EM_ANDAMENTO = "Em andamento"
STATUS_ESCALONADA = "Escalonada"
STATUS_RESOLVIDA = "Resolvida"
STATUS_CHOICES = (
    STATUS_ABERTA,
    STATUS_EM_ANDAMENTO,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
)

FILE_VERSION = 1


def classificacao_label(classificacao):
    days = CLASSIFICACOES.get(classificacao)
    if days is None:
        return classificacao
    unit = "dia" if days == 1 else "dias"
    return f"{classificacao} | {days} {unit}"


def prazo_para(classificacao, inicio):
    """Deadline for a classification, counted in calendar days."""
    return inicio + timedelta(days=CLASSIFICACOES.get(classificacao, 0))


def format_date(value):
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def format_datetime(value):
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return ""


@dataclass
class Escalonamento:
    data: str
    superior: str
    prazo: str
    motivo: str = ""


@dataclass
class NaoConformidade:
    id: int
    projeto: str = ""
    descricao: str = ""
    classificacao: str = ""
    acao_corretiva: str = ""
    responsavel: str = ""
    email_responsavel: str = ""
    responsavel_qa: str = ""
    data_solicitacao: str = ""
    prazo: str = ""
    status: str = STATUS_ABERTA
    observacoes: str = ""
    conclusao_em: str = ""
    escalonamentos: list = field(default_factory=list)

    @property
    def numero_escalonamento(self):
        return len(self.escalonamentos)

    @property
    def prazo_atual(self):
        """Deadline in force: the last escalation's one, or the original."""
        if self.escalonamentos:
            return self.escalonamentos[-1].prazo
        return self.prazo

    def vencida(self, hoje=None):
        if self.status == STATUS_RESOLVIDA or not self.prazo_atual:
            return False
        hoje = hoje or date.today()
        return date.fromisoformat(self.prazo_atual) < hoje

    def escalonar(self, superior, novo_prazo, motivo="", quando=None):
        quando = quando or datetime.now()
        self.escalonamentos.append(
            Escalonamento(
                data=quando.isoformat(timespec="minutes"),
                superior=superior,
                prazo=novo_prazo.isoformat(),
                motivo=motivo,
            )
        )
        self.status = STATUS_ESCALONADA

    def resolver(self, quando=None):
        quando = quando or datetime.now()
        self.status = STATUS_RESOLVIDA
        self.conclusao_em = quando.isoformat(timespec="minutes")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        escalonamentos = [
            Escalonamento(**item) for item in data.pop("escalonamentos", [])
        ]
        return cls(**data, escalonamentos=escalonamentos)


def save_json(path, items):
    payload = {
        "versao": FILE_VERSION,
        "nao_conformidades": [item.to_dict() for item in items],
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def load_json(path):
    with open(path, encoding="utf-8") as file:
        payload = json.load(file)
    return [
        NaoConformidade.from_dict(item)
        for item in payload.get("nao_conformidades", [])
    ]


class NcTableModel(QAbstractTableModel):
    """Read-only table of non-conformities; edits go through dialogs."""

    COLUMNS = (
        ("id", "ID"),
        ("projeto", "Projeto"),
        ("descricao", "Descrição"),
        ("classificacao", "Classificação"),
        ("responsavel", "Responsável"),
        ("data_solicitacao", "1ª Solicitação"),
        ("prazo_atual", "Prazo atual"),
        ("numero_escalonamento", "Nº Escalonamento"),
        ("status", "Status"),
    )

    _CENTERED = {
        "id",
        "data_solicitacao",
        "prazo_atual",
        "numero_escalonamento",
        "status",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    @property
    def items(self):
        return list(self._items)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        nc = self._items[index.row()]
        key = self.COLUMNS[index.column()][0]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(nc, key)

        if role == Qt.ItemDataRole.BackgroundRole:
            if nc.vencida():
                return QColor("#fecaca")
            if nc.status == STATUS_RESOLVIDA:
                return QColor("#bbf7d0")
            if nc.status == STATUS_ESCALONADA:
                return QColor("#fde68a")

        if role == Qt.ItemDataRole.ForegroundRole and (
            nc.vencida()
            or nc.status in (STATUS_RESOLVIDA, STATUS_ESCALONADA)
        ):
            return QColor("#111827")

        if role == Qt.ItemDataRole.ToolTipRole and key == "descricao":
            return nc.descricao

        if (
            role == Qt.ItemDataRole.TextAlignmentRole
            and key in self._CENTERED
        ):
            return Qt.AlignmentFlag.AlignCenter

        return None

    def _display_value(self, nc, key):
        if key in ("data_solicitacao", "prazo_atual"):
            return format_date(getattr(nc, key))
        if key == "status" and nc.vencida():
            return f"{nc.status} (vencida)"
        return getattr(nc, key)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return self.COLUMNS[section][1]
        return None

    def nc_at(self, row):
        return self._items[row]

    def next_id(self):
        return max((nc.id for nc in self._items), default=0) + 1

    def add(self, nc):
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(nc)
        self.endInsertRows()
        return row

    def refresh_row(self, row):
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, len(self.COLUMNS) - 1),
        )

    def refresh_all(self):
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, len(self.COLUMNS) - 1),
            )

    def remove_rows(self, rows):
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._items[row]
                self.endRemoveRows()

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()
