import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

# Classification (priority-complexity) -> business days to resolve the NC,
# as defined in the course's "Checklist de Processo e Produto" example.
# A warning ("Advertência") has no deadline and is never escalated.
CLASSIFICACAO_ADVERTENCIA = "Advertência"
CLASSIFICACOES = {
    CLASSIFICACAO_ADVERTENCIA: 0,
    "Baixa-Simples": 4,
    "Baixa-Complexa": 5,
    "Baixa-Severa": 6,
    "Baixa-Extrema": 7,
    "Média-Simples": 3,
    "Média-Complexa": 4,
    "Média-Severa": 5,
    "Média-Extrema": 6,
    "Alta-Simples": 2,
    "Alta-Complexa": 3,
    "Alta-Severa": 4,
    "Alta-Extrema": 5,
    "Urgente-Simples": 1,
    "Urgente-Complexa": 2,
    "Urgente-Severa": 3,
    "Urgente-Extrema": 4,
}

# Escalation goes at most two levels up: responsible -> leader -> manager.
MAX_ESCALONAMENTOS = 2
NIVEIS_ESCALONAMENTO = {
    1: "1º nível (líder / gerente de projeto)",
    2: "2º nível (gerência superior)",
}

FORMAS_RESOLUCAO = (
    "Produto/processo ajustado ao padrão",
    "Padrão/processo alterado para ser eficaz",
    "Fechamento por exceção (decisão executiva)",
)

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

# Row colors of the NC table, also used by the legend under it.
COR_VENCIDA = "#ff0000"
COR_ESCALONADA = "#ffcc00"
COR_RESOLVIDA = "#00ff59"
COR_TEXTO_DESTACADO = "#111827"


def classificacao_label(classificacao, uteis=True):
    """Label like "Média-Simples | 3 dias úteis"; the PDF template omits "úteis"."""
    days = CLASSIFICACOES.get(classificacao)
    if days is None:
        return classificacao
    if days == 0:
        return f"{classificacao} | Não se aplica"
    unit = "dia" if days == 1 else "dias"
    if uteis:
        unit += " útil" if days == 1 else " úteis"
    return f"{classificacao} | {days} {unit}"


def tem_prazo(classificacao):
    return CLASSIFICACOES.get(classificacao, 0) > 0


def prazo_para(classificacao, inicio):
    """Deadline for a classification, counted in business days (Mon-Fri)."""
    prazo = inicio
    restantes = CLASSIFICACOES.get(classificacao, 0)
    while restantes > 0:
        prazo += timedelta(days=1)
        if prazo.weekday() < 5:
            restantes -= 1
    return prazo


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
    email_superior: str = ""


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
    forma_resolucao: str = ""
    solucao_adotada: str = ""
    evidencia_resolucao: str = ""
    escalonamentos: list = field(default_factory=list)
    comunicacoes: list = field(default_factory=list)

    @property
    def numero_escalonamento(self):
        return len(self.escalonamentos)

    @property
    def prazo_atual(self):
        """Deadline in force: the last escalation's one, or the original."""
        if self.escalonamentos:
            return self.escalonamentos[-1].prazo
        return self.prazo

    @property
    def ultima_comunicacao(self):
        return self.comunicacoes[-1]["data"] if self.comunicacoes else ""

    def vencida(self, hoje=None):
        if self.status == STATUS_RESOLVIDA or not self.prazo_atual:
            return False
        hoje = hoje or date.today()
        return date.fromisoformat(self.prazo_atual) < hoje

    @property
    def limite_escalonamento_atingido(self):
        return self.numero_escalonamento >= MAX_ESCALONAMENTOS

    def motivo_bloqueio_escalonamento(self):
        """Why this NC can't be escalated, or "" when it can."""
        if self.status == STATUS_RESOLVIDA:
            return "Essa NC já está resolvida."
        if not tem_prazo(self.classificacao):
            return "Advertências não têm prazo e não são escalonadas."
        if self.limite_escalonamento_atingido:
            return (
                f"Essa NC já foi escalonada {MAX_ESCALONAMENTOS} vezes, "
                "que é o limite. Resolva ou faça o fechamento por exceção."
            )
        return ""

    def novo_prazo_escalonamento(self, hoje=None):
        """New deadline reuses the original resolution time, from today."""
        return prazo_para(self.classificacao, hoje or date.today())

    def escalonar(self, superior, motivo="", email_superior="", quando=None):
        bloqueio = self.motivo_bloqueio_escalonamento()
        if bloqueio:
            raise ValueError(bloqueio)
        if not superior.strip():
            raise ValueError("Informe o superior responsável.")

        quando = quando or datetime.now()
        self.escalonamentos.append(
            Escalonamento(
                data=quando.isoformat(timespec="minutes"),
                superior=superior.strip(),
                prazo=self.novo_prazo_escalonamento(quando.date()).isoformat(),
                motivo=motivo,
                email_superior=email_superior.strip(),
            )
        )
        self.status = STATUS_ESCALONADA

    def resolver(self, forma, solucao, evidencia, quando=None):
        if self.status == STATUS_RESOLVIDA:
            raise ValueError("Essa NC já está resolvida.")
        if forma not in FORMAS_RESOLUCAO:
            raise ValueError("Forma de resolução inválida.")
        if not solucao.strip() or not evidencia.strip():
            raise ValueError("Informe a solução adotada e a comprovação.")

        quando = quando or datetime.now()
        self.status = STATUS_RESOLVIDA
        self.conclusao_em = quando.isoformat(timespec="minutes")
        self.forma_resolucao = forma
        self.solucao_adotada = solucao.strip()
        self.evidencia_resolucao = evidencia.strip()

    def destinatarios(self):
        """Responsible person, plus the current superior once escalated."""
        emails = [self.email_responsavel]
        if self.escalonamentos:
            emails.append(self.escalonamentos[-1].email_superior)
        return [email for email in emails if email]

    def registrar_comunicacao(self, destinatario, arquivo, quando=None):
        quando = quando or datetime.now()
        self.comunicacoes.append(
            {
                "data": quando.isoformat(timespec="minutes"),
                "destinatario": destinatario,
                "escalonamento": self.numero_escalonamento,
                "arquivo": arquivo,
            }
        )

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
        ("ultima_comunicacao", "Último e-mail"),
    )

    _CENTERED = {
        "id",
        "data_solicitacao",
        "prazo_atual",
        "numero_escalonamento",
        "status",
        "ultima_comunicacao",
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
                return QColor(COR_VENCIDA)
            if nc.status == STATUS_RESOLVIDA:
                return QColor(COR_RESOLVIDA)
            if nc.status == STATUS_ESCALONADA:
                return QColor(COR_ESCALONADA)

        if role == Qt.ItemDataRole.ForegroundRole and (
            nc.vencida()
            or nc.status in (STATUS_RESOLVIDA, STATUS_ESCALONADA)
        ):
            return QColor(COR_TEXTO_DESTACADO)

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
        if key == "ultima_comunicacao":
            return format_datetime(nc.ultima_comunicacao)
        if key == "status" and nc.vencida():
            if nc.limite_escalonamento_atingido:
                return f"{nc.status} (vencida, limite de escalonamento)"
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
