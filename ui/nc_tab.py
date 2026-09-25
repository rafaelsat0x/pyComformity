from datetime import date
from smtplib import SMTPAuthenticationError

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from models.nc_model import (
    CLASSIFICACOES,
    COR_ESCALONADA,
    COR_RESOLVIDA,
    COR_TEXTO_DESTACADO,
    COR_VENCIDA,
    FORMAS_RESOLUCAO,
    MAX_ESCALONAMENTOS,
    NIVEIS_ESCALONAMENTO,
    STATUS_ABERTA,
    STATUS_EM_ANDAMENTO,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NaoConformidade,
    NcTableModel,
    classificacao_label,
    format_date,
    format_datetime,
    load_json,
    prazo_para,
    save_json,
    tem_prazo,
)
from services.email_sender import (
    PROVEDORES,
    EmailConfig,
    build_message,
    friendly_error,
    load_config,
    save_config,
    send_message,
    test_login,
)
from services.nc_communication import (
    default_pdf_name,
    export_communication,
    open_email,
)


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
        # A request can't be dated in the future, or it would never be overdue.
        self.data_solicitacao.setMaximumDate(_to_qdate(max(solicitacao, date.today())))
        self.prazo = QLabel()
        self.status = QComboBox()
        self.status.addItems([STATUS_ABERTA, STATUS_EM_ANDAMENTO])
        self.observacoes = _text_edit(nc.observacoes, 50)

        # Escalated/resolved NCs change status only through their buttons.
        if nc.status in (STATUS_ESCALONADA, STATUS_RESOLVIDA):
            self.status.addItem(nc.status)
            self.status.setEnabled(False)
        self.status.setCurrentText(nc.status)

        self.classificacao.currentIndexChanged.connect(self._update_prazo)
        self.data_solicitacao.dateChanged.connect(self._update_prazo)
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
        if nc.escalonamentos:
            form.addRow(
                "Prazo atual (escalonamento)",
                QLabel(format_date(nc.prazo_atual)),
            )
        if nc.status == STATUS_RESOLVIDA:
            for label, value in (
                ("Concluída em", format_datetime(nc.conclusao_em)),
                ("Forma de resolução", nc.forma_resolucao),
                ("Solução adotada", nc.solucao_adotada),
                ("Comprovação", nc.evidencia_resolucao),
            ):
                text = QLabel(value)
                text.setWordWrap(True)
                form.addRow(label, text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _prazo(self):
        """Original deadline from the classification, or None for warnings."""
        classificacao = self.classificacao.currentData()
        if not tem_prazo(classificacao):
            return None
        inicio = _from_qdate(self.data_solicitacao.date())
        return prazo_para(classificacao, inicio)

    def _update_prazo(self):
        prazo = self._prazo()
        self.prazo.setText(
            prazo.strftime("%d/%m/%Y") + " (dias úteis)" if prazo else "Não se aplica"
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

        if _from_qdate(self.data_solicitacao.date()) > date.today():
            QMessageBox.warning(
                self,
                "Data inválida",
                "A data da 1ª solicitação não pode estar no futuro.",
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
        prazo = self._prazo()
        nc.prazo = prazo.isoformat() if prazo else ""
        nc.status = self.status.currentText()
        nc.observacoes = self.observacoes.toPlainText().strip()
        self.accept()


class EscalonarDialog(QDialog):
    """Asks who the NC is escalated to; the new deadline follows the rule."""

    def __init__(self, nc, parent=None):
        super().__init__(parent)
        nivel = nc.numero_escalonamento + 1
        self.setWindowTitle(f"Escalonar NC #{nc.id}")
        self.setMinimumWidth(480)

        situacao = "vencida" if nc.vencida() else "dentro do prazo"
        resumo = QLabel(
            f"<b>{nc.descricao}</b><br>"
            f"Responsável: {nc.responsavel} (continua responsável)<br>"
            f"Prazo atual: {format_date(nc.prazo_atual)} ({situacao})<br>"
            f"Escalonamento: <b>{NIVEIS_ESCALONAMENTO[nivel]}</b> "
            f"de {MAX_ESCALONAMENTOS}"
        )
        resumo.setWordWrap(True)

        self.superior = QLineEdit()
        self.superior.setPlaceholderText("Superior imediato de quem não resolveu")
        self.email_superior = QLineEdit()
        self.email_superior.setPlaceholderText("superior@empresa.com")
        novo_prazo = QLabel(
            f"{format_date(nc.novo_prazo_escalonamento().isoformat())} "
            f"(mesmo tempo da NC original: {classificacao_label(nc.classificacao)})"
        )
        novo_prazo.setWordWrap(True)
        self.motivo = _text_edit(
            "Prazo de resolução expirado." if nc.vencida() else ""
        )

        form = QFormLayout()
        form.addRow("Superior responsável*", self.superior)
        form.addRow("E-mail do superior", self.email_superior)
        form.addRow("Novo prazo", novo_prazo)
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
            self.motivo.toPlainText().strip(),
            self.email_superior.text().strip(),
        )


class ResolverDialog(QDialog):
    """Registers how the NC was solved and the proof of the resolution."""

    def __init__(self, nc, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Resolver NC #{nc.id}")
        self.setMinimumWidth(480)

        resumo = QLabel(f"<b>{nc.descricao}</b>")
        resumo.setWordWrap(True)

        self.forma = QComboBox()
        self.forma.addItems(FORMAS_RESOLUCAO)
        self.solucao = _text_edit()
        self.solucao.setPlaceholderText("O que foi feito para resolver a NC")
        self.evidencia = _text_edit()
        self.evidencia.setPlaceholderText(
            "Como a resolução foi conferida (documento, versão, link, registro...)"
        )

        form = QFormLayout()
        form.addRow("Forma de resolução", self.forma)
        form.addRow("Solução adotada*", self.solucao)
        form.addRow("Comprovação*", self.evidencia)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Resolver")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(resumo)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.solucao.toPlainText().strip() or not self.evidencia.toPlainText().strip():
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Informe a solução adotada e a comprovação da resolução.",
            )
            return
        self.accept()

    def values(self):
        return (
            self.forma.currentText(),
            self.solucao.toPlainText().strip(),
            self.evidencia.toPlainText().strip(),
        )


class _WaitCursor:
    """Shows the busy cursor while a blocking SMTP call runs."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *_exc):
        QApplication.restoreOverrideCursor()


class EmailConfigDialog(QDialog):
    """SMTP settings for sending NC e-mails straight from the app."""

    def __init__(self, config, senha="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar envio de e-mail")
        self.setMinimumWidth(480)

        self.provedor = QComboBox()
        self.provedor.addItems(list(PROVEDORES))
        self.provedor.setCurrentText(config.provedor)
        self.servidor = QLineEdit(config.servidor)
        self.porta = QSpinBox()
        self.porta.setRange(1, 65535)
        self.porta.setValue(config.porta)
        self.remetente = QLineEdit(config.remetente)
        self.remetente.setPlaceholderText("voce@gmail.com")
        self.nome = QLineEdit(config.nome)
        self.nome.setPlaceholderText("Nome que aparece no e-mail")
        self.copia = QLineEdit(config.copia)
        self.copia.setPlaceholderText("Opcional, ex: qa@empresa.com")
        self.senha = QLineEdit(senha)
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.senha.setPlaceholderText("Senha de app")
        self.provedor.currentTextChanged.connect(self._apply_provedor)

        ajuda = QLabel(
            "<b>Gmail:</b> ative a verificação em duas etapas e gere uma "
            "<i>senha de app</i> em myaccount.google.com/apppasswords.<br>"
            "<b>Outlook:</b> a conta precisa ter SMTP AUTH liberado pela "
            "organização; contas pessoais do outlook.com podem recusar.<br>"
            "A senha fica só na memória enquanto o app estiver aberto."
        )
        ajuda.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Provedor", self.provedor)
        form.addRow("Servidor SMTP", self.servidor)
        form.addRow("Porta", self.porta)
        form.addRow("E-mail remetente*", self.remetente)
        form.addRow("Nome do remetente", self.nome)
        form.addRow("Cópia (Cc)", self.copia)
        form.addRow("Senha", self.senha)

        test_button = QPushButton("Testar conexão")
        test_button.clicked.connect(self._test)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.addButton(test_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ajuda)
        layout.addWidget(buttons)

    def _apply_provedor(self, provedor):
        servidor, porta = PROVEDORES[provedor]
        if servidor:
            self.servidor.setText(servidor)
            self.porta.setValue(porta)

    def config(self):
        return EmailConfig(
            provedor=self.provedor.currentText(),
            servidor=self.servidor.text().strip(),
            porta=self.porta.value(),
            remetente=self.remetente.text().strip(),
            nome=self.nome.text().strip(),
            copia=self.copia.text().strip(),
        )

    def password(self):
        return self.senha.text()

    def _test(self):
        config = self.config()
        if not config.completa or not self.password():
            QMessageBox.warning(
                self,
                "Testar conexão",
                "Preencha servidor, e-mail remetente e senha.",
            )
            return
        try:
            with _WaitCursor():
                test_login(config, self.password())
        except Exception as error:
            QMessageBox.critical(self, "Testar conexão", friendly_error(error))
            return
        QMessageBox.information(self, "Testar conexão", "Login feito com sucesso.")

    def _accept(self):
        if not self.config().completa:
            QMessageBox.warning(
                self,
                "Campos obrigatórios",
                "Preencha servidor e e-mail remetente.",
            )
            return
        self.accept()


class NcTab(QWidget):
    """Registration, follow-up, escalation and communication of NCs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = None
        self._email_config = load_config()
        self._smtp_password = ""

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
            ("Resolver", self._resolve_nc),
            ("Gerar comunicação", self._communicate_nc),
            ("Excluir", self._delete_nc),
        )
        button_layout = QHBoxLayout()
        for label, slot in actions:
            button = QPushButton(label)
            button.clicked.connect(slot)
            button_layout.addWidget(button)
        button_layout.addStretch()

        for label, slot in (
            ("Configurar e-mail", self._configure_email),
            ("Abrir...", self._open_file),
            ("Salvar", self._save_file),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            button_layout.addWidget(button)

        legend = QLabel(
            f"<span style='background:{COR_VENCIDA}; color:{COR_TEXTO_DESTACADO}'>"
            "&nbsp;vencida&nbsp;</span> "
            f"<span style='background:{COR_ESCALONADA}; color:{COR_TEXTO_DESTACADO}'>"
            "&nbsp;escalonada&nbsp;</span> "
            f"<span style='background:{COR_RESOLVIDA}; color:{COR_TEXTO_DESTACADO}'>"
            "&nbsp;resolvida&nbsp;</span>"
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
        widths = (50, 160, 330, 200, 160, 110, 110, 130, 150, 130)
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
        bloqueio = nc.motivo_bloqueio_escalonamento()
        if bloqueio:
            QMessageBox.information(self, "Escalonar NC", bloqueio)
            return

        if not nc.vencida():
            answer = QMessageBox.question(
                self,
                "Escalonar NC",
                "O prazo dessa NC ainda não expirou. Escalonar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        dialog = EscalonarDialog(nc, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        superior, motivo, email_superior = dialog.values()
        nc.escalonar(superior, motivo, email_superior)
        self._after_change(row)

        answer = QMessageBox.question(
            self,
            "Escalonar NC",
            "NC escalonada. Gerar e enviar a comunicação do escalonamento "
            "(com a NC original anexada) agora?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._communicate(nc, row)

    def _resolve_nc(self):
        row = self._selected_row("Resolver NC")
        if row is None:
            return
        nc = self.model.nc_at(row)
        if nc.status == STATUS_RESOLVIDA:
            QMessageBox.information(self, "Resolver NC", "Essa NC já está resolvida.")
            return

        dialog = ResolverDialog(nc, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        nc.resolver(*dialog.values())
        self._after_change(row)

        if nc.destinatarios():
            answer = QMessageBox.question(
                self,
                "Resolver NC",
                "NC resolvida. Comunicar a resolução aos envolvidos?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._communicate(nc, row)

    def _communicate_nc(self):
        row = self._selected_row("Gerar comunicação")
        if row is not None:
            self._communicate(self.model.nc_at(row), row)

    def _configure_email(self):
        dialog = EmailConfigDialog(self._email_config, self._smtp_password, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._email_config = dialog.config()
        self._smtp_password = dialog.password()
        save_config(self._email_config)
        return True

    def _ask_password(self):
        if self._smtp_password:
            return True
        senha, ok = QInputDialog.getText(
            self,
            "Senha do e-mail",
            f"Senha de app de {self._email_config.remetente}:",
            QLineEdit.EchoMode.Password,
        )
        if ok and senha:
            self._smtp_password = senha
        return bool(self._smtp_password)

    def _communicate(self, nc, row):
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
            paths = [str(item) for item in export_communication(nc, path)]
        except OSError as error:
            QMessageBox.critical(self, "Gerar comunicação", str(error))
            return
        salvos = "\n".join(paths)

        if not nc.destinatarios():
            QMessageBox.information(
                self,
                "Gerar comunicação",
                f"PDF(s) salvo(s) em:\n{salvos}\n\n"
                "Cadastre o e-mail do responsável para enviar a comunicação.",
            )
            return

        if not self._email_config.completa:
            answer = QMessageBox.question(
                self,
                "Gerar comunicação",
                "O envio automático ainda não foi configurado. Configurar agora?\n\n"
                "Se escolher Não, o e-mail abre no seu cliente para anexar o PDF.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._configure_email()

        if self._email_config.completa and self._ask_password():
            self._send_email(nc, row, paths)
            return

        if not open_email(nc, paths):
            QMessageBox.warning(
                self,
                "Gerar comunicação",
                f"PDF(s) salvo(s) em:\n{salvos}\n\n"
                "Não consegui abrir o cliente de e-mail.",
            )
            return

        QMessageBox.information(
            self,
            "Gerar comunicação",
            f"PDF(s) salvo(s) em:\n{salvos}\n\n"
            "O e-mail foi aberto no seu cliente. Anexe os PDFs antes de enviar.",
        )

    def _send_email(self, nc, row, pdf_paths):
        try:
            message = build_message(self._email_config, nc, pdf_paths)
            with _WaitCursor():
                send_message(self._email_config, self._smtp_password, message)
        except Exception as error:
            # A rejected password must be asked again on the next try.
            if isinstance(error, SMTPAuthenticationError):
                self._smtp_password = ""
            QMessageBox.critical(
                self,
                "Enviar e-mail",
                "Os PDFs foram salvos, mas o e-mail não foi enviado.\n\n"
                f"{friendly_error(error)}",
            )
            return

        destinatarios = ", ".join(nc.destinatarios())
        nc.registrar_comunicacao(destinatarios, pdf_paths[0])
        self._after_change(row)
        QMessageBox.information(
            self,
            "Enviar e-mail",
            f"Comunicação da NC #{nc.id} enviada para {destinatarios} "
            f"com {len(pdf_paths)} PDF(s) em anexo.",
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

        def linha(nc):
            return (
                f"#{nc.id} - {nc.responsavel} "
                f"(prazo {format_date(nc.prazo_atual)}, "
                f"{nc.numero_escalonamento} escalonamento(s))"
            )

        escalar = [nc for nc in vencidas if not nc.limite_escalonamento_atingido]
        esgotadas = [nc for nc in vencidas if nc.limite_escalonamento_atingido]
        partes = []
        if escalar:
            partes.append(
                "Devem ser escalonadas ao superior imediato:\n"
                + "\n".join(linha(nc) for nc in escalar)
            )
        if esgotadas:
            partes.append(
                f"Já passaram pelos {MAX_ESCALONAMENTOS} níveis de escalonamento "
                "(resolver ou fechar por exceção):\n"
                + "\n".join(linha(nc) for nc in esgotadas)
            )
        QMessageBox.warning(
            self,
            "NCs vencidas",
            f"{len(vencidas)} NC(s) passaram do prazo.\n\n" + "\n\n".join(partes),
        )
