from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from models.nc_model import (
    CLASSIFICACOES,
    STATUS_ABERTA,
    STATUS_EM_ANDAMENTO,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NaoConformidade,
    NcTableModel,
    classificacao_label,
    format_date,
    load_json,
    prazo_para,
    save_json,
)
from services.nc_communication import default_pdf_name, export_pdf, open_email


def _to_qdate(value):
    return QDate(value.year, value.month, value.day)


def _from_qdate(value):
    return date(value.year(), value.month(), value.day())


def _date_edit(value):
    editor = QDateEdit(_to_qdate(value))
    editor.setCalendarPopup(True)
    editor.setDisplayFormat("dd/MM/yyyy")
    return editor


def _text_edit(value="", height=70):
    editor = QPlainTextEdit(value)
    editor.setFixedHeight(height)
    return editor


class NcDialog(QDialog):
    """Form used to register a new NC or edit an existing one."""

    def __init__(self, nc, parent=None):
        super().__init__(parent)
        self._nc = nc
        is_new = not nc.data_solicitacao
        self.setWindowTitle("Nova NC" if is_new else f"Editar NC #{nc.id}")
        self.setMinimumWidth(520)

        solicitacao = (
            date.fromisoformat(nc.data_solicitacao)
            if nc.data_solicitacao
            else date.today()
        )
        prazo = date.fromisoformat(nc.prazo) if nc.prazo else solicitacao

        self.projeto = QLineEdit(nc.projeto)
        self.descricao = _text_edit(nc.descricao)
        self.classificacao = QComboBox()
        for nome in CLASSIFICACOES:
            self.classificacao.addItem(classificacao_label(nome), nome)
        if nc.classificacao in CLASSIFICACOES:
            self.classificacao.setCurrentIndex(
                list(CLASSIFICACOES).index(nc.classificacao)
            )
        self.acao_corretiva = _text_edit(nc.acao_corretiva)
        self.responsavel = QLineEdit(nc.responsavel)
        self.email_responsavel = QLineEdit(nc.email_responsavel)
        self.email_responsavel.setPlaceholderText("nome@empresa.com")
        self.responsavel_qa = QLineEdit(nc.responsavel_qa)
        self.data_solicitacao = _date_edit(solicitacao)
        self.prazo = _date_edit(prazo)
        self.status = QComboBox()
        self.status.addItems([STATUS_ABERTA, STATUS_EM_ANDAMENTO])
        self.observacoes = _text_edit(nc.observacoes, 50)

        # Escalated/resolved NCs change status only through their buttons.
        if nc.status in (STATUS_ESCALONADA, STATUS_RESOLVIDA):
            self.status.addItem(nc.status)
            self.status.setEnabled(False)
        self.status.setCurrentText(nc.status)

        # After an escalation the deadline in force lives in the history.
        if nc.escalonamentos:
            self.prazo.setEnabled(False)
            self.prazo.setToolTip("Prazo original; o atual vem do escalonamento.")

        self.classificacao.currentIndexChanged.connect(self._update_prazo)
        self.data_solicitacao.dateChanged.connect(self._update_prazo)
        if is_new:
            self._update_prazo()

        form = QFormLayout()
        form.addRow("Projeto*", self.projeto)
        form.addRow("Descrição*", self.descricao)
        form.addRow("Classificação*", self.classificacao)
        form.addRow("Ação corretiva indicada", self.acao_corretiva)
        form.addRow("Responsável pela resolução*", self.responsavel)
        form.addRow("E-mail do responsável", self.email_responsavel)
        form.addRow("Responsável por QA", self.responsavel_qa)
        form.addRow("Data da 1ª solicitação", self.data_solicitacao)
        form.addRow("Prazo de resolução", self.prazo)
        form.addRow("Status", self.status)
        form.addRow("Observações", self.observacoes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_prazo(self):
        if not self.prazo.isEnabled():
            return
        inicio = _from_qdate(self.data_solicitacao.date())
        self.prazo.setDate(
            _to_qdate(prazo_para(self.classificacao.currentData(), inicio))
        )

    def _accept(self):
        faltando = [
            nome
            for nome, valor in (
                ("Projeto", self.projeto.text()),
                ("Descrição", self.descricao.toPlainText()),
                ("Responsável pela resolução", self.responsavel.text()),
            )
            if not valor.strip()
        ]
        if faltando:
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha: " + ", ".join(faltando) + ".",
            )
            return

        if self.prazo.date() < self.data_solicitacao.date():
            QMessageBox.warning(
                self,
                "Prazo inválido",
                "O prazo não pode ser anterior à data da solicitação.",
            )
            return

        nc = self._nc
        nc.projeto = self.projeto.text().strip()
        nc.descricao = self.descricao.toPlainText().strip()
        nc.classificacao = self.classificacao.currentData()
        nc.acao_corretiva = self.acao_corretiva.toPlainText().strip()
        nc.responsavel = self.responsavel.text().strip()
        nc.email_responsavel = self.email_responsavel.text().strip()
        nc.responsavel_qa = self.responsavel_qa.text().strip()
        nc.data_solicitacao = _from_qdate(
            self.data_solicitacao.date()
        ).isoformat()
        nc.prazo = _from_qdate(self.prazo.date()).isoformat()
        nc.status = self.status.currentText()
        nc.observacoes = self.observacoes.toPlainText().strip()
        self.accept()


class EscalonarDialog(QDialog):
    """Asks who the NC is escalated to and the new deadline."""

    def __init__(self, nc, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Escalonar NC #{nc.id}")
        self.setMinimumWidth(460)

        situacao = "vencida" if nc.vencida() else "dentro do prazo"
        resumo = QLabel(
            f"<b>{nc.descricao}</b><br>"
            f"Responsável: {nc.responsavel} · "
            f"Prazo atual: {format_date(nc.prazo_atual)} ({situacao})<br>"
            f"Escalonamentos anteriores: {nc.numero_escalonamento}"
        )
        resumo.setWordWrap(True)

        ultimo_superior = (
            nc.escalonamentos[-1].superior if nc.escalonamentos else ""
        )
        self.superior = QLineEdit(ultimo_superior)
        self.novo_prazo = _date_edit(prazo_para(nc.classificacao, date.today()))
        self.novo_prazo.setMinimumDate(_to_qdate(date.today()))
        self.motivo = _text_edit(
            "Prazo de resolução expirado." if nc.vencida() else ""
        )

        form = QFormLayout()
        form.addRow("Superior responsável*", self.superior)
        form.addRow("Novo prazo", self.novo_prazo)
        form.addRow("Motivo", self.motivo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Escalonar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(resumo)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.superior.text().strip():
            QMessageBox.warning(
                self,
                "Campo obrigatório",
                "Informe o superior responsável.",
            )
            return
        self.accept()

    def values(self):
        return (
            self.superior.text().strip(),
            _from_qdate(self.novo_prazo.date()),
            self.motivo.toPlainText().strip(),
        )


class NcTab(QWidget):
    """Registration, follow-up, escalation and communication of NCs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = None

        self.model = NcTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setWordWrap(True)
        self.table.doubleClicked.connect(self._edit_nc)
        self.table.horizontalHeader().setStyleSheet(
            "QHeaderView::section {"
            "background-color: #d1d5db;"
            "color: #111827;"
            "font-weight: 600;"
            "padding: 6px;"
            "border: 1px solid #9ca3af;"
            "}"
        )
        self._set_initial_column_widths()

        self.summary = QLabel()

        actions = (
            ("Nova NC", self._new_nc),
            ("Editar", self._edit_nc),
            ("Escalonar", self._escalate_nc),
            ("Marcar resolvida", self._resolve_nc),
            ("Gerar comunicação", self._communicate_nc),
            ("Excluir", self._delete_nc),
        )
        button_layout = QHBoxLayout()
        for label, slot in actions:
            button = QPushButton(label)
            button.clicked.connect(slot)
            button_layout.addWidget(button)
        button_layout.addStretch()

        for label, slot in (("Abrir...", self._open_file), ("Salvar", self._save_file)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            button_layout.addWidget(button)

        legend = QLabel(
            "<span style='background:#fecaca'>&nbsp;vencida&nbsp;</span> "
            "<span style='background:#fde68a'>&nbsp;escalonada&nbsp;</span> "
            "<span style='background:#bbf7d0'>&nbsp;resolvida&nbsp;</span>"
        )

        footer = QHBoxLayout()
        footer.addWidget(self.summary)
        footer.addStretch()
        footer.addWidget(legend)

        layout = QVBoxLayout(self)
        layout.addLayout(button_layout)
        layout.addWidget(self.table)
        layout.addLayout(footer)

        self._update_summary()

    def _set_initial_column_widths(self):
        widths = (50, 160, 360, 170, 170, 110, 110, 130, 150)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    def _selected_row(self, action):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(
                self,
                action,
                "Selecione uma NC na tabela.",
            )
            return None
        return rows[0].row()

    def _update_summary(self):
        items = self.model.items
        vencidas = sum(nc.vencida() for nc in items)
        resolvidas = sum(nc.status == STATUS_RESOLVIDA for nc in items)
        escalonadas = sum(nc.status == STATUS_ESCALONADA for nc in items)
        self.summary.setText(
            f"{len(items)} NCs · {len(items) - resolvidas} em aberto · "
            f"{escalonadas} escalonadas · {vencidas} vencidas · "
            f"{resolvidas} resolvidas"
        )

    def _after_change(self, row=None):
        if row is None:
            self.model.refresh_all()
        else:
            self.model.refresh_row(row)
        self._update_summary()

    def _new_nc(self):
        nc = NaoConformidade(id=self.model.next_id())
        if NcDialog(nc, self).exec() != QDialog.DialogCode.Accepted:
            return
        row = self.model.add(nc)
        self.table.selectRow(row)
        self._after_change(row)

    def _edit_nc(self, *_args):
        row = self._selected_row("Editar NC")
        if row is None:
            return
        if NcDialog(self.model.nc_at(row), self).exec() == QDialog.DialogCode.Accepted:
            self._after_change(row)

    def _escalate_nc(self):
        row = self._selected_row("Escalonar NC")
        if row is None:
            return
        nc = self.model.nc_at(row)
        if nc.status == STATUS_RESOLVIDA:
            QMessageBox.information(
                self,
                "Escalonar NC",
                "Essa NC já está resolvida.",
            )
            return

        dialog = EscalonarDialog(nc, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        nc.escalonar(*dialog.values())
        self._after_change(row)

        answer = QMessageBox.question(
            self,
            "Escalonar NC",
            "NC escalonada. Gerar a comunicação do escalonamento agora?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._communicate(nc)

    def _resolve_nc(self):
        row = self._selected_row("Marcar resolvida")
        if row is None:
            return
        nc = self.model.nc_at(row)
        if nc.status == STATUS_RESOLVIDA:
            return
        answer = QMessageBox.question(
            self,
            "Marcar resolvida",
            f"Confirmar a resolução da NC #{nc.id}?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            nc.resolver()
            self._after_change(row)

    def _communicate_nc(self):
        row = self._selected_row("Gerar comunicação")
        if row is not None:
            self._communicate(self.model.nc_at(row))

    def _communicate(self, nc):
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Salvar solicitação de resolução",
            default_pdf_name(nc),
            "PDF (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        try:
            export_pdf(nc, path)
        except OSError as error:
            QMessageBox.critical(self, "Gerar comunicação", str(error))
            return

        if not nc.email_responsavel:
            QMessageBox.information(
                self,
                "Gerar comunicação",
                f"PDF salvo em:\n{path}\n\n"
                "Cadastre o e-mail do responsável para abrir o e-mail pronto.",
            )
            return

        if not open_email(nc, path):
            QMessageBox.warning(
                self,
                "Gerar comunicação",
                f"PDF salvo em:\n{path}\n\n"
                "Não consegui abrir o cliente de e-mail.",
            )
            return

        QMessageBox.information(
            self,
            "Gerar comunicação",
            f"PDF salvo em:\n{path}\n\n"
            "O e-mail foi aberto no seu cliente. Anexe o PDF antes de enviar.",
        )

    def _delete_nc(self):
        row = self._selected_row("Excluir NC")
        if row is None:
            return
        answer = QMessageBox.question(
            self,
            "Excluir NC",
            f"Excluir a NC #{self.model.nc_at(row).id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.model.remove_rows([row])
            self._update_summary()

    def _save_file(self):
        path = self._file_path
        if not path:
            path, _filter = QFileDialog.getSaveFileName(
                self,
                "Salvar NCs",
                "nao_conformidades.json",
                "JSON (*.json)",
            )
            if not path:
                return
            if not path.lower().endswith(".json"):
                path += ".json"

        try:
            save_json(path, self.model.items)
        except OSError as error:
            QMessageBox.critical(self, "Salvar", str(error))
            return
        self._file_path = path
        QMessageBox.information(self, "Salvar", f"NCs salvas em:\n{path}")

    def _open_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Abrir NCs",
            "",
            "JSON (*.json)",
        )
        if not path:
            return

        try:
            items = load_json(path)
        except (OSError, ValueError, TypeError, KeyError) as error:
            QMessageBox.critical(
                self,
                "Abrir",
                f"Não consegui ler o arquivo:\n{error}",
            )
            return

        self._file_path = path
        self.model.set_items(items)
        self._update_summary()
        self._warn_overdue()

    def _warn_overdue(self):
        vencidas = [nc for nc in self.model.items if nc.vencida()]
        if not vencidas:
            return
        linhas = "\n".join(
            f"#{nc.id} - {nc.responsavel} (prazo {format_date(nc.prazo_atual)})"
            for nc in vencidas
        )
        QMessageBox.warning(
            self,
            "NCs vencidas",
            f"{len(vencidas)} NC(s) passaram do prazo e devem ser "
            f"escalonadas:\n\n{linhas}",
        )
