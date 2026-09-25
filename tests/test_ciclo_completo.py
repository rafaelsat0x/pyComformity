"""End-to-end checks: colors, full NC life cycle and edge cases."""

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (starts the Qt application)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from models.nc_model import (
    COR_ESCALONADA,
    COR_RESOLVIDA,
    COR_VENCIDA,
    FORMAS_RESOLUCAO,
    STATUS_EM_ANDAMENTO,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NcTableModel,
    load_json,
    save_json,
)
from services import email_sender
from services.nc_communication import export_communication
from tests.helpers import make_nc
from tests.test_communication import FakeSMTP
from ui import nc_tab
from ui.nc_tab import NcDialog, NcTab

BACKGROUND = Qt.ItemDataRole.BackgroundRole


def _row_color(model, row=0):
    color = model.data(model.index(row, 0), BACKGROUND)
    return color.name() if color else None


class CoresTests(unittest.TestCase):
    """The colors chosen by the team for each NC state."""

    def setUp(self):
        self.model = NcTableModel()

    def test_vencida_em_vermelho(self):
        self.model.add(make_nc())  # deadline 19/03/2026, already past
        self.assertEqual(_row_color(self.model), COR_VENCIDA)
        self.assertEqual(COR_VENCIDA, "#ff0000")

    def test_escalonada_em_amarelo(self):
        nc = make_nc()
        nc.escalonar("Gerente")  # new deadline in the future
        self.model.add(nc)
        self.assertEqual(_row_color(self.model), COR_ESCALONADA)
        self.assertEqual(COR_ESCALONADA, "#ffcc00")

    def test_resolvida_em_verde(self):
        nc = make_nc()
        nc.resolver(FORMAS_RESOLUCAO[0], "ok", "ok")
        self.model.add(nc)
        self.assertEqual(_row_color(self.model), COR_RESOLVIDA)
        self.assertEqual(COR_RESOLVIDA, "#00ff59")

    def test_vencida_tem_prioridade_sobre_escalonada(self):
        nc = make_nc()
        nc.escalonar("Gerente", quando=datetime(2026, 3, 20))  # also overdue
        self.model.add(nc)
        self.assertEqual(_row_color(self.model), COR_VENCIDA)

    def test_nc_no_prazo_fica_sem_cor(self):
        hoje = date.today().isoformat()
        self.model.add(make_nc(data_solicitacao=hoje))
        self.assertIsNone(_row_color(self.model))

    def test_legenda_usa_as_mesmas_cores(self):
        tab = NcTab()
        legenda = tab.findChildren(nc_tab.QLabel)
        texto = " ".join(label.text() for label in legenda)
        for cor in (COR_VENCIDA, COR_ESCALONADA, COR_RESOLVIDA):
            self.assertIn(cor, texto)


class CicloCompletoTests(unittest.TestCase):
    """Register -> overdue -> escalate x2 -> communicate -> resolve -> reopen."""

    def setUp(self):
        FakeSMTP.sent = []
        self.config = email_sender.EmailConfig(remetente="qa@gmail.com")
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = Path(self.folder.name)

    def _comunicar(self, nc, nome):
        paths = export_communication(nc, self.dir / nome)
        message = email_sender.build_message(self.config, nc, paths)
        with mock.patch.object(email_sender.smtplib, "SMTP", FakeSMTP):
            email_sender.send_message(self.config, "senha-certa", message)
        nc.registrar_comunicacao(", ".join(nc.destinatarios()), str(paths[0]))
        return FakeSMTP.sent[-1]

    def test_ciclo_de_vida_inteiro(self):
        nc = make_nc()

        # 1. registered and first communication, only to the responsible
        email = self._comunicar(nc, "nc_esc0.pdf")
        self.assertEqual(email["To"], "luis@example.com")
        self.assertEqual(len(list(email.iter_attachments())), 1)

        # 2. deadline expires
        self.assertTrue(nc.vencida(date(2026, 3, 20)))

        # 3. first escalation: responsible + leader, original NC attached
        nc.escalonar(
            "Gerente de Projeto", "Prazo expirado.", "gp@example.com",
            quando=datetime(2026, 3, 20, 9, 0),
        )
        email = self._comunicar(nc, "nc_esc1.pdf")
        self.assertEqual(email["To"], "luis@example.com, gp@example.com")
        self.assertEqual(
            [p.get_filename() for p in email.iter_attachments()],
            ["nc_esc1.pdf", "nc_esc1_NC_original.pdf"],
        )

        # 4. new deadline also expires: second (and last) level
        self.assertTrue(nc.vencida(date(2026, 3, 26)))
        nc.escalonar(
            "Mauricio F.", "Sem retorno.", "mauricio@example.com",
            quando=datetime(2026, 3, 26, 9, 0),
        )
        email = self._comunicar(nc, "nc_esc2.pdf")
        self.assertEqual(email["To"], "luis@example.com, mauricio@example.com")
        self.assertEqual(nc.prazo_atual, "2026-03-31")
        self.assertEqual(nc.responsavel, "Luis S")
        with self.assertRaises(ValueError):
            nc.escalonar("Diretor")

        # 5. resolved with proof, and the resolution is communicated
        nc.resolver(
            FORMAS_RESOLUCAO[0], "Itens renomeados.", "Baseline 1.3",
            quando=datetime(2026, 3, 30, 15, 0),
        )
        email = self._comunicar(nc, "nc_resolvida.pdf")
        self.assertIn("NC resolvida", email["Subject"])
        self.assertFalse(nc.vencida(date(2030, 1, 1)))

        # 6. everything survives saving and reopening
        save_json(self.dir / "ncs.json", [nc])
        reaberta = load_json(self.dir / "ncs.json")[0]
        self.assertEqual(reaberta, nc)
        self.assertEqual(reaberta.status, STATUS_RESOLVIDA)
        self.assertEqual(reaberta.numero_escalonamento, 2)
        self.assertEqual(len(reaberta.comunicacoes), 4)
        self.assertEqual(len(FakeSMTP.sent), 4)


class CasosDeBordaTests(unittest.TestCase):
    def test_editar_nc_escalonada_mantem_prazo_do_escalonamento(self):
        nc = make_nc()
        nc.escalonar("Gerente", quando=datetime(2026, 3, 20, 9, 0))
        dialog = NcDialog(nc)
        self.assertFalse(dialog.status.isEnabled())
        dialog.observacoes.setPlainText("Atualizado.")
        dialog._accept()
        self.assertEqual(nc.status, STATUS_ESCALONADA)
        self.assertEqual(nc.prazo_atual, "2026-03-25")
        self.assertEqual(nc.observacoes, "Atualizado.")

    def test_status_em_andamento_continua_vencendo(self):
        nc = make_nc(status=STATUS_EM_ANDAMENTO)
        self.assertTrue(nc.vencida(date(2026, 3, 20)))

    def test_id_nao_repete_depois_de_excluir(self):
        model = NcTableModel()
        model.add(make_nc(id=1))
        model.add(make_nc(id=2))
        model.remove_rows([0])
        self.assertEqual(model.next_id(), 3)

    def test_superior_sem_email_manda_so_pro_responsavel(self):
        nc = make_nc()
        nc.escalonar("Gerente")
        self.assertEqual(nc.destinatarios(), ["luis@example.com"])

    def test_nc_sem_email_nao_tem_destinatario(self):
        self.assertEqual(make_nc(email_responsavel="").destinatarios(), [])

    def test_prazo_no_dia_ainda_nao_venceu(self):
        nc = make_nc(data_solicitacao=(date.today() - timedelta(days=30)).isoformat())
        nc.prazo = date.today().isoformat()
        self.assertFalse(nc.vencida())

    def test_aba_bloqueia_escalonar_advertencia(self):
        tab = NcTab()
        tab.model.add(make_nc(classificacao="Advertência", prazo=""))
        tab.table.selectRow(0)
        with mock.patch.object(nc_tab.QMessageBox, "information") as info, \
                mock.patch.object(nc_tab.EscalonarDialog, "exec") as exec_:
            tab._escalate_nc()
        exec_.assert_not_called()
        self.assertIn("Advertências", info.call_args.args[2])

    def test_aba_sem_selecao_avisa(self):
        tab = NcTab()
        with mock.patch.object(nc_tab.QMessageBox, "information") as info:
            tab._resolve_nc()
        self.assertIn("Selecione", info.call_args.args[2])

    def test_arquivo_invalido_mostra_erro(self):
        tab = NcTab()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as file:
            file.write("isso não é json")
        self.addCleanup(Path(file.name).unlink)
        with mock.patch.object(
            nc_tab.QFileDialog, "getOpenFileName", return_value=(file.name, "")
        ), mock.patch.object(nc_tab.QMessageBox, "critical") as critical:
            tab._open_file()
        critical.assert_called_once()
        self.assertEqual(tab.model.rowCount(), 0)

    def test_cancelar_nova_nc_nao_adiciona(self):
        tab = NcTab()
        with mock.patch.object(
            NcDialog, "exec", return_value=QDialog.DialogCode.Rejected
        ):
            tab._new_nc()
        self.assertEqual(tab.model.rowCount(), 0)

    def test_excluir_pede_confirmacao(self):
        tab = NcTab()
        tab.model.add(make_nc())
        tab.table.selectRow(0)
        with mock.patch.object(
            nc_tab.QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            tab._delete_nc()
        self.assertEqual(tab.model.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
