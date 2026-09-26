"""R08/R09/R12: NC communication (template, escalation e-mail, sending)."""

import smtplib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (starts the Qt application)
from PySide6.QtPdf import QPdfDocument

from models.nc_model import FORMAS_RESOLUCAO
from services import email_sender
from services.nc_communication import (
    build_email,
    export_communication,
    export_pdf,
    mailto_url,
)
from tests.helpers import make_nc


def _pdf_text(nc):
    """Renders the NC to a real PDF and reads its text back."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "nc.pdf"
        export_pdf(nc, path)
        document = QPdfDocument()
        document.load(str(path))
        pages = document.pageCount()
        size = document.pagePointSize(0)
        text = "\n".join(document.getAllText(page).text() for page in range(pages))
        document.close()
    return text, pages, size


class TemplateTests(unittest.TestCase):
    """Fields of 'Solicitação de Resolução de Não Conformidade' v2.0."""

    def test_pdf_tem_todos_os_campos_do_template(self):
        texto, _pages, _size = _pdf_text(make_nc())
        for trecho in (
            "Solicitação de Resolução de Não Conformidade",
            "Projeto:",
            "Projeto Exemplo",
            "Responsável pela Resolução:",
            "Luis S",
            "Data da 1a Solicitação:",
            "16/03/2026",
            "Prazo de Resolução:",
            "19/03/2026",
            "Nº de Escalonamento:",
            "Responsável por QA:",
            "Vinicius",
            "Descrição",
            "Classificação",
            "Ação Corretiva Indicada",
            "Média-Simples | 3 dias",
            "Histórico de Escalonamento",
            "Superior Responsável",
            "Prazo para Resolução",
            "Nenhum",
            "Observações:",
            "Template de Solicitação de Resolução de Não Conformidade - Versão 2.0",
        ):
            self.assertIn(trecho, texto)

    def test_pdf_em_a4_paisagem_de_uma_pagina(self):
        _texto, pages, size = _pdf_text(make_nc())
        self.assertEqual(pages, 1)
        self.assertGreater(size.width(), size.height())
        self.assertAlmostEqual(size.width(), 841.9, delta=1)

    def test_historico_mostra_nivel_superior_e_prazo(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", quando=datetime(2026, 3, 20, 9, 0))
        texto, _pages, _size = _pdf_text(nc)
        self.assertIn("1º nível", texto)
        self.assertIn("Gerente de Projeto", texto)
        self.assertIn("25/03/2026", texto)
        self.assertNotIn("Nenhum", texto)

    def test_nc_original_nao_tem_escalonamentos(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", quando=datetime(2026, 3, 20, 9, 0))
        with tempfile.TemporaryDirectory() as folder:
            _atual, original = export_communication(nc, Path(folder) / "nc.pdf")
            document = QPdfDocument()
            document.load(str(original))
            texto = document.getAllText(0).text()
            document.close()
        self.assertIn("Nenhum", texto)
        self.assertIn("19/03/2026", texto)
        self.assertNotIn("Gerente de Projeto", texto)


class ComunicacaoEscalonamentoTests(unittest.TestCase):
    """Slide: escalation mail goes to responsible + superior, original attached."""

    def test_escalonamento_gera_pdf_atual_e_nc_original(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", email_superior="gp@example.com")
        with tempfile.TemporaryDirectory() as folder:
            paths = export_communication(nc, Path(folder) / "nc.pdf")
            self.assertEqual([p.name for p in paths], ["nc.pdf", "nc_NC_original.pdf"])
            for path in paths:
                self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_nc_sem_escalonamento_gera_um_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = export_communication(make_nc(), Path(folder) / "nc.pdf")
            self.assertEqual(len(paths), 1)

    def test_email_de_escalonamento(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", email_superior="gp@example.com")
        assunto, corpo = build_email(nc, ["nc.pdf", "nc_NC_original.pdf"])
        self.assertIn("escalonamento 1", assunto)
        self.assertIn("Luis S e Gerente de Projeto", corpo)
        self.assertIn("continua sendo de Luis S", corpo)
        self.assertIn("NC original está anexada", corpo)

    def test_mailto_vai_para_responsavel_e_superior(self):
        nc = make_nc()
        nc.escalonar("Gerente", email_superior="gp@example.com")
        url = mailto_url(nc).toString()
        self.assertTrue(url.startswith("mailto:luis@example.com,gp@example.com?"))

    def test_email_de_resolucao(self):
        nc = make_nc()
        nc.resolver(FORMAS_RESOLUCAO[0], "Arquivos renomeados.", "Baseline 1.2")
        assunto, corpo = build_email(nc)
        self.assertIn("NC resolvida", assunto)
        self.assertIn("Solução adotada: Arquivos renomeados.", corpo)
        self.assertIn("Comprovação: Baseline 1.2", corpo)


class FakeSMTP:
    """Records what would have been sent, without touching the network."""

    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if password != "senha-certa":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, message):
        FakeSMTP.sent.append(message)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class EnvioAutomaticoTests(unittest.TestCase):
    """R12: automatic sending through Gmail/Outlook SMTP."""

    def setUp(self):
        FakeSMTP.sent = []
        self.config = email_sender.EmailConfig(
            remetente="qa@gmail.com", nome="QA", copia="lider@example.com"
        )

    def test_envia_com_anexos_para_responsavel_e_superior(self):
        nc = make_nc()
        nc.escalonar("Gerente", email_superior="gp@example.com")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            email_sender.smtplib, "SMTP", FakeSMTP
        ):
            paths = export_communication(nc, Path(folder) / "nc.pdf")
            message = email_sender.build_message(self.config, nc, paths)
            email_sender.send_message(self.config, "senha-certa", message)

        enviado = FakeSMTP.sent[0]
        self.assertEqual(enviado["To"], "luis@example.com, gp@example.com")
        self.assertEqual(enviado["Cc"], "lider@example.com")
        self.assertEqual(
            [part.get_filename() for part in enviado.iter_attachments()],
            ["nc.pdf", "nc_NC_original.pdf"],
        )

    def test_senha_errada_vira_mensagem_amigavel(self):
        with mock.patch.object(email_sender.smtplib, "SMTP", FakeSMTP):
            with self.assertRaises(smtplib.SMTPAuthenticationError) as ctx:
                email_sender.test_login(self.config, "errada")
        self.assertIn("senha de app", email_sender.friendly_error(ctx.exception))

    def test_provedores_gmail_e_outlook(self):
        self.assertEqual(email_sender.PROVEDORES["Gmail"], ("smtp.gmail.com", 587))
        self.assertEqual(
            email_sender.PROVEDORES["Outlook / Office 365"],
            ("smtp.office365.com", 587),
        )


if __name__ == "__main__":
    unittest.main()
