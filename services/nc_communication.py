from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QMarginsF, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from models.nc_model import (
    NIVEIS_ESCALONAMENTO,
    STATUS_ABERTA,
    STATUS_RESOLVIDA,
    classificacao_label,
    format_date,
    format_datetime,
)

TEMPLATE_FOOTER = (
    "Template de Solicitação de Resolução de Não Conformidade - Versão 2.0"
)

# Layout copied from the course's "Exemplo_Comunicacao_NC.pdf" (an Excel
# sheet printed on A4 landscape). Every measure is in millimetres from the
# page's top-left corner.
LEFT = 13.3
RIGHT = 205.7
LABEL_RIGHT = 58.8
HEADER_TOP = 26.9
ROW_HEIGHT = 9.2
BAR_HEIGHT = 5.4
PADDING = 0.8
DESC_COLUMNS = (LEFT, 86.3, 125.8, RIGHT)
HIST_COLUMNS = (LEFT, 86.3, 142.2, RIGHT)
DESC_MIN_HEIGHT = 36.7
HIST_MIN_HEIGHT = 16.0
FOOTER_TOP = 166.5

GRAY = QColor("#bfbfbf")
LINE = QColor("#d9d9d9")
DIVIDER = QColor("#a6a6a6")
FONT_FAMILIES = ["Calibri", "Carlito", "Liberation Sans", "Arial"]


def original_nc(nc):
    """The NC as it was first communicated, before any escalation."""
    return replace(
        nc,
        escalonamentos=[],
        comunicacoes=[],
        status=STATUS_ABERTA,
        conclusao_em="",
        forma_resolucao="",
        solucao_adotada="",
        evidencia_resolucao="",
    )


def _font(size, bold=False):
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(size)
    font.setBold(bold)
    # Ligatures like "ti" become a single glyph and break copy/search in the PDF.
    for tag in ("liga", "clig", "dlig"):
        font.setFeature(QFont.Tag(tag), 0)
    return font


class _Sheet:
    """Draws spreadsheet-like cells on a PDF page using millimetres."""

    def __init__(self, writer, painter):
        self._px = writer.resolution() / 25.4
        self._writer = writer
        self.painter = painter
        self.regular = _font(10)
        self.bold = _font(10, bold=True)

    def rect(self, x1, y1, x2, y2):
        return QRectF(
            x1 * self._px, y1 * self._px, (x2 - x1) * self._px, (y2 - y1) * self._px
        )

    def fill(self, x1, y1, x2, y2, color=GRAY):
        self.painter.fillRect(self.rect(x1, y1, x2, y2), color)

    def line(self, x1, y1, x2, y2, color=LINE):
        pen = QPen(color)
        pen.setWidthF(0.2 * self._px)
        self.painter.setPen(pen)
        self.painter.drawLine(
            self.rect(x1, y1, x2, y2).topLeft(), self.rect(x1, y1, x2, y2).bottomRight()
        )

    def text(self, x1, y1, x2, y2, value, font=None, align=None):
        align = align or (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.painter.setPen(QColor("#000000"))
        self.painter.setFont(font or self.regular)
        self.painter.drawText(
            self.rect(x1 + PADDING, y1 + PADDING / 2, x2 - PADDING, y2),
            int(align | Qt.TextFlag.TextWordWrap),
            str(value or ""),
        )

    def text_height(self, value, width, font=None):
        """Height in mm that wrapped text needs inside a cell."""
        if not value:
            return 0
        metrics = QFontMetricsF(font or self.regular, self._writer)
        box = metrics.boundingRect(
            QRectF(0, 0, (width - 2 * PADDING) * self._px, 1e6),
            int(Qt.TextFlag.TextWordWrap),
            str(value),
        )
        return box.height() / self._px + PADDING

    def bar(self, y, columns, titles):
        self.fill(columns[0], y, columns[-1], y + BAR_HEIGHT)
        for (x1, x2), title in zip(zip(columns, columns[1:]), titles):
            self.text(
                x1, y, x2, y + BAR_HEIGHT, title, self.bold,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            )
        return y + BAR_HEIGHT

    def rows(self, y, columns, rows, min_height, first_align=None):
        """Body under a bar: one line of cells per row, split by dividers."""
        top = y
        for row in rows:
            height = max(
                self.text_height(value, x2 - x1)
                for (x1, x2), value in zip(zip(columns, columns[1:]), row)
            ) + PADDING
            for index, ((x1, x2), value) in enumerate(zip(zip(columns, columns[1:]), row)):
                align = first_align if index == 0 and first_align else None
                self.text(x1, y, x2, y + height, value, align=align)
            y += height
        bottom = max(y, top + min_height)
        for x in columns[1:-1]:
            self.line(x, top, x, bottom, DIVIDER)
        return bottom


def _draw_header(sheet, nc):
    sheet.text(
        LEFT, 20.3, RIGHT, HEADER_TOP,
        "Solicitação de Resolução de Não Conformidade",
        _font(14, bold=True),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
    )

    label_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    value_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    linhas = (
        ("Projeto:", nc.projeto),
        ("Responsável pela Resolução:", nc.responsavel),
        ("Data da 1a Solicitação:", format_date(nc.data_solicitacao)),
        ("Nº de Escalonamento:", str(nc.numero_escalonamento)),
        ("Responsável por QA:", nc.responsavel_qa),
    )
    sheet.line(LABEL_RIGHT, HEADER_TOP, RIGHT, HEADER_TOP)
    for index, (label, value) in enumerate(linhas):
        y1 = HEADER_TOP + index * ROW_HEIGHT
        y2 = y1 + ROW_HEIGHT
        sheet.fill(LEFT, y1, LABEL_RIGHT, y2)
        sheet.text(LEFT, y1, LABEL_RIGHT, y2, label, sheet.bold, label_align)
        if index == 2:
            prazo_x1, prazo_x2 = DESC_COLUMNS[1], HIST_COLUMNS[2]
            sheet.text(LABEL_RIGHT, y1, prazo_x1, y2, value, align=value_align)
            sheet.fill(prazo_x1, y1, prazo_x2, y2)
            sheet.text(prazo_x1, y1, prazo_x2, y2, "Prazo de Resolução:", sheet.bold, label_align)
            sheet.text(
                prazo_x2, y1, RIGHT, y2,
                format_date(nc.prazo_atual) or "Não se aplica",
                align=value_align,
            )
        else:
            sheet.text(LABEL_RIGHT, y1, RIGHT, y2, value, align=value_align)
        sheet.line(LABEL_RIGHT, y2, RIGHT, y2)
    return HEADER_TOP + len(linhas) * ROW_HEIGHT


def _historico(nc):
    rows = []
    for nivel, item in enumerate(nc.escalonamentos, start=1):
        quando = f"{NIVEIS_ESCALONAMENTO.get(nivel, f'{nivel}º nível')} - {format_datetime(item.data)}"
        if item.motivo:
            quando += f"\n{item.motivo}"
        rows.append((quando, item.superior, format_date(item.prazo)))
    return rows


def _draw(sheet, nc):
    y = _draw_header(sheet, nc) + 5.5

    y = sheet.bar(y, DESC_COLUMNS, ("Descrição", "Classificação", "Ação Corretiva Indicada"))
    y = sheet.rows(
        y,
        DESC_COLUMNS,
        [(nc.descricao, classificacao_label(nc.classificacao, uteis=False), nc.acao_corretiva)],
        DESC_MIN_HEIGHT,
    )

    y = sheet.bar(
        y, HIST_COLUMNS,
        ("Histórico de Escalonamento", "Superior Responsável", "Prazo para Resolução"),
    )
    historico = _historico(nc)
    if historico:
        y = sheet.rows(y, HIST_COLUMNS, historico, HIST_MIN_HEIGHT)
    else:
        y = sheet.rows(
            y, HIST_COLUMNS, [("Nenhum", "", "")], HIST_MIN_HEIGHT,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )

    # Not in the course template: registers how a resolved NC was closed.
    if nc.status == STATUS_RESOLVIDA:
        y = sheet.bar(
            y, HIST_COLUMNS,
            ("Conclusão", "Forma de Resolução", "Solução Adotada / Comprovação"),
        )
        y = sheet.rows(
            y,
            HIST_COLUMNS,
            [(
                format_datetime(nc.conclusao_em),
                nc.forma_resolucao,
                f"{nc.solucao_adotada}\nComprovação: {nc.evidencia_resolucao}",
            )],
            HIST_MIN_HEIGHT,
        )

    sheet.fill(LEFT, y, RIGHT, y + BAR_HEIGHT)
    sheet.text(
        LEFT, y, RIGHT, y + BAR_HEIGHT, "Observações:",
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    y += BAR_HEIGHT
    altura = sheet.text_height(nc.observacoes, RIGHT - LEFT, sheet.bold)
    sheet.text(LEFT, y, RIGHT, y + altura + PADDING, nc.observacoes, sheet.bold)
    y += altura

    footer_top = max(FOOTER_TOP, y + 8)
    sheet.text(
        LEFT, footer_top, RIGHT, footer_top + 5, TEMPLATE_FOOTER, _font(9.2),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
    )


def default_pdf_name(nc):
    return f"Solicitacao_NC_{nc.id:03d}_esc{nc.numero_escalonamento}.pdf"


def export_pdf(nc, path):
    writer = QPdfWriter(str(path))
    writer.setTitle(f"Solicitação de Resolução de NC #{nc.id}")
    writer.setResolution(300)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Millimeter,
        )
    )

    painter = QPainter(writer)
    try:
        _draw(_Sheet(writer, painter), nc)
    finally:
        painter.end()


def export_communication(nc, path):
    """Writes the NC request PDF; an escalation also gets the original NC.

    Returns every PDF written, main one first, so all can be attached.
    """
    path = Path(path)
    export_pdf(nc, path)
    paths = [path]
    if nc.escalonamentos:
        original = path.with_name(f"{path.stem}_NC_original{path.suffix}")
        export_pdf(original_nc(nc), original)
        paths.append(original)
    return paths


def build_email(nc, pdf_paths=()):
    """Subject and body for the NC e-mail."""
    assunto = f"[NC #{nc.id}] Solicitação de resolução - {nc.projeto}"
    if nc.status == STATUS_RESOLVIDA:
        assunto = f"[NC #{nc.id}] NC resolvida - {nc.projeto}"
    elif nc.numero_escalonamento:
        assunto += f" (escalonamento {nc.numero_escalonamento})"

    if nc.escalonamentos:
        ultimo = nc.escalonamentos[-1]
        nivel = NIVEIS_ESCALONAMENTO.get(
            nc.numero_escalonamento, f"{nc.numero_escalonamento}º nível"
        )
        linhas = [f"Olá, {nc.responsavel} e {ultimo.superior}.", ""]
        if nc.status != STATUS_RESOLVIDA:
            linhas += [
                "A não conformidade abaixo não foi resolvida no prazo e foi "
                f"escalonada ao {nivel}.",
                f"A responsabilidade pela resolução continua sendo de "
                f"{nc.responsavel}.",
            ]
    else:
        linhas = [f"Olá, {nc.responsavel}.", ""]
        if nc.status != STATUS_RESOLVIDA:
            linhas.append(
                f"Foi registrada uma não conformidade no projeto {nc.projeto}."
            )

    if nc.status == STATUS_RESOLVIDA:
        linhas.append(
            f"A não conformidade abaixo foi resolvida em "
            f"{format_datetime(nc.conclusao_em)}."
        )

    linhas += [
        "",
        f"Descrição: {nc.descricao}",
        f"Classificação: {classificacao_label(nc.classificacao)}",
        f"Ação corretiva indicada: {nc.acao_corretiva}",
        f"Prazo de resolução: {format_date(nc.prazo_atual) or 'Não se aplica'}",
        f"Nº de escalonamento: {nc.numero_escalonamento}",
    ]
    if nc.escalonamentos:
        linhas.append(f"Superior responsável: {nc.escalonamentos[-1].superior}")
    if nc.status == STATUS_RESOLVIDA:
        linhas += [
            f"Forma de resolução: {nc.forma_resolucao}",
            f"Solução adotada: {nc.solucao_adotada}",
            f"Comprovação: {nc.evidencia_resolucao}",
        ]
    if nc.observacoes:
        linhas += ["", f"Observações: {nc.observacoes}"]
    if pdf_paths:
        nomes = ", ".join(Path(item).name for item in pdf_paths)
        texto = "Seguem em anexo" if len(pdf_paths) > 1 else "Segue em anexo"
        linhas += ["", f"{texto}: {nomes}."]
        if nc.escalonamentos:
            linhas.append("A NC original está anexada para referência.")
    linhas += ["", "Atenciosamente,", nc.responsavel_qa]

    return assunto, "\n".join(linhas)


def mailto_url(nc, pdf_paths=()):
    assunto, corpo = build_email(nc, pdf_paths)
    destinatarios = ",".join(quote(email, safe="@") for email in nc.destinatarios())
    query = f"subject={quote(assunto)}&body={quote(corpo)}"
    return QUrl.fromEncoded(f"mailto:{destinatarios}?{query}".encode("ascii"))


def open_email(nc, pdf_paths=()):
    return QDesktopServices.openUrl(mailto_url(nc, pdf_paths))
