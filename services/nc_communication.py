from html import escape
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QDesktopServices, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from models.nc_model import classificacao_label, format_date, format_datetime

TEMPLATE_FOOTER = (
    "Template de Solicitação de Resolução de Não Conformidade - Versão 2.0"
)


def _text(value):
    """Escapes user text for the HTML report, keeping line breaks."""
    return escape(value or "").replace("\n", "<br>")


def build_html(nc):
    if nc.escalonamentos:
        historico = "".join(
            "<tr>"
            f"<td>{format_datetime(item.data)}"
            f"{'<br><i>' + _text(item.motivo) + '</i>' if item.motivo else ''}"
            "</td>"
            f"<td>{_text(item.superior)}</td>"
            f"<td>{format_date(item.prazo)}</td>"
            "</tr>"
            for item in nc.escalonamentos
        )
    else:
        historico = '<tr><td colspan="3" align="center">Nenhum</td></tr>'

    return f"""
<html>
<head>
<style>
  body {{ font-family: sans-serif; font-size: 10pt; color: #111827; }}
  h1 {{ font-size: 16pt; text-align: center; margin-bottom: 0; }}
  h2 {{ font-size: 12pt; text-align: center; font-weight: normal; margin-top: 4px; }}
  table.grid {{ border-collapse: collapse; width: 100%; }}
  table.grid th {{ background-color: #d1d5db; border: 1px solid #9ca3af; padding: 6px; }}
  table.grid td {{ border: 1px solid #9ca3af; padding: 6px; vertical-align: top; }}
  .footer {{ font-size: 8pt; color: #6b7280; text-align: right; }}
</style>
</head>
<body>
<h1>Solicitação de Resolução de Não Conformidade</h1>
<h2>Projeto: {_text(nc.projeto)}</h2>

<table width="100%" cellpadding="4">
  <tr>
    <td colspan="2"><b>Responsável pela Resolução:</b> {_text(nc.responsavel)}</td>
  </tr>
  <tr>
    <td><b>Data da 1ª Solicitação:</b> {format_date(nc.data_solicitacao)}</td>
    <td><b>Prazo de Resolução:</b> {format_date(nc.prazo_atual)}</td>
  </tr>
  <tr>
    <td><b>Nº de Escalonamento:</b> {nc.numero_escalonamento}</td>
    <td><b>Status:</b> {_text(nc.status)}</td>
  </tr>
  <tr>
    <td colspan="2"><b>Responsável por QA:</b> {_text(nc.responsavel_qa)}</td>
  </tr>
</table>
<br>

<table class="grid">
  <tr><th>Descrição</th><th>Classificação</th><th>Ação Corretiva Indicada</th></tr>
  <tr>
    <td>{_text(nc.descricao)}</td>
    <td align="center">{_text(classificacao_label(nc.classificacao))}</td>
    <td>{_text(nc.acao_corretiva)}</td>
  </tr>
</table>
<br>

<table class="grid">
  <tr><th>Histórico de Escalonamento</th><th>Superior Responsável</th><th>Prazo para Resolução</th></tr>
  {historico}
</table>
<br>

<p><b>Observações:</b><br>{_text(nc.observacoes)}</p>
<br>
<p class="footer">{TEMPLATE_FOOTER}</p>
</body>
</html>
"""


def default_pdf_name(nc):
    return f"Solicitacao_NC_{nc.id:03d}_esc{nc.numero_escalonamento}.pdf"


def export_pdf(nc, path):
    writer = QPdfWriter(str(path))
    writer.setTitle(f"Solicitação de Resolução de NC #{nc.id}")
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter,
        )
    )

    document = QTextDocument()
    document.setHtml(build_html(nc))
    document.print_(writer)


def build_email(nc, pdf_path=None):
    """Subject and body for the NC e-mail; the PDF must be attached by hand."""
    assunto = f"[NC #{nc.id}] Solicitação de resolução - {nc.projeto}"
    if nc.numero_escalonamento:
        assunto += f" (escalonamento {nc.numero_escalonamento})"

    linhas = [
        f"Olá, {nc.responsavel}.",
        "",
        f"Foi registrada uma não conformidade no projeto {nc.projeto}.",
        "",
        f"Descrição: {nc.descricao}",
        f"Classificação: {classificacao_label(nc.classificacao)}",
        f"Ação corretiva indicada: {nc.acao_corretiva}",
        f"Prazo de resolução: {format_date(nc.prazo_atual)}",
        f"Nº de escalonamento: {nc.numero_escalonamento}",
    ]
    if nc.escalonamentos:
        ultimo = nc.escalonamentos[-1]
        linhas.append(f"Superior responsável: {ultimo.superior}")
    if nc.observacoes:
        linhas += ["", f"Observações: {nc.observacoes}"]
    if pdf_path:
        linhas += [
            "",
            f"Segue em anexo a solicitação ({Path(pdf_path).name}).",
        ]
    linhas += ["", "Atenciosamente,", nc.responsavel_qa]

    return assunto, "\n".join(linhas)


def mailto_url(nc, pdf_path=None):
    assunto, corpo = build_email(nc, pdf_path)
    destinatario = quote(nc.email_responsavel.strip(), safe="@")
    query = f"subject={quote(assunto)}&body={quote(corpo)}"
    return QUrl.fromEncoded(f"mailto:{destinatario}?{query}".encode("ascii"))


def open_email(nc, pdf_path=None):
    return QDesktopServices.openUrl(mailto_url(nc, pdf_path))
