"""UI flows of the NC tab, driven without showing windows."""

import unittest
from datetime import date
from unittest import mock

import tests  # noqa: F401  (starts the Qt application)
from PySide6.QtWidgets import QDialog, QMessageBox

from models.nc_model import (
    FORMAS_RESOLUCAO,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NaoConformidade,
    prazo_para,
)
from tests.helpers import make_nc
from ui import nc_tab
from ui.nc_tab import EscalonarDialog, NcDialog, NcTab, ResolverDialog, _to_qdate

NO = QMessageBox.StandardButton.No
YES = QMessageBox.StandardButton.Yes


class NcDialogTests(unittest.TestCase):
    def test_nova_nc_calcula_prazo_pela_classificacao(self):
        nc = NaoConformidade(id=1)
        dialog = NcDialog(nc)
        dialog.projeto.setText("Projeto Exemplo")
        dialog.descricao.setPlainText("Checklist sem responsável.")
        dialog.responsavel.setText("Luis S")
        dialog.classificacao.setCurrentIndex(
            dialog.classificacao.findData("Alta-Complexa")
        )
        dialog._accept()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        esperado = prazo_para("Alta-Complexa", date.today()).isoformat()
        self.assertEqual(nc.prazo, esperado)
        self.assertEqual(nc.data_solicitacao, date.today().isoformat())

    def test_advertencia_fica_sem_prazo(self):
        nc = NaoConformidade(id=1)
        dialog = NcDialog(nc)
        dialog.projeto.setText("P")
        dialog.descricao.setPlainText("d")
        dialog.responsavel.setText("r")
        dialog.classificacao.setCurrentIndex(
            dialog.classificacao.findData("Advertência")
        )
        self.assertEqual(dialog.prazo.text(), "Não se aplica")
        dialog._accept()
        self.assertEqual(nc.prazo, "")

    def test_data_da_solicitacao_nao_pode_ser_futura(self):
        nc = NaoConformidade(id=1)
        dialog = NcDialog(nc)
        self.assertEqual(dialog.data_solicitacao.maximumDate(), _to_qdate(date.today()))
        dialog.data_solicitacao.setDate(_to_qdate(date(date.today().year + 1, 1, 1)))
        self.assertEqual(dialog.data_solicitacao.date(), _to_qdate(date.today()))

    def test_campos_obrigatorios(self):
        nc = NaoConformidade(id=1)
        dialog = NcDialog(nc)
        with mock.patch.object(nc_tab.QMessageBox, "warning") as warning:
            dialog._accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(nc.descricao, "")


class TabFlowTests(unittest.TestCase):
    """Register -> follow up -> escalate twice -> resolve, through the tab."""

    def setUp(self):
        self.tab = NcTab()
        self.nc = make_nc()  # deadline 19/03/2026, already overdue
        self.tab.model.add(self.nc)
        self.tab._after_change(0)
        self.tab.table.selectRow(0)

    def _escalate(self, superior):
        def fake_exec(dialog):
            dialog.superior.setText(superior)
            dialog.email_superior.setText("chefe@example.com")
            return QDialog.DialogCode.Accepted

        def fake_question(_parent, _title, text, *_args):
            # Confirms early escalation, skips sending the communication.
            return YES if "ainda não expirou" in text else NO

        with mock.patch.object(EscalonarDialog, "exec", fake_exec), \
                mock.patch.object(nc_tab.QMessageBox, "question", fake_question), \
                mock.patch.object(nc_tab.QMessageBox, "information") as info:
            self.tab._escalate_nc()
        return info

    def test_tabela_mostra_nc_vencida(self):
        status = self.tab.model.data(self.tab.model.index(0, 8))
        self.assertEqual(status, "Aberta (vencida)")
        self.assertIn("1 vencidas", self.tab.summary.text())

    def test_escalonamento_ate_o_limite(self):
        self._escalate("Gerente de Projeto")
        self.assertEqual(self.nc.status, STATUS_ESCALONADA)
        self.assertEqual(self.nc.numero_escalonamento, 1)

        self._escalate("Mauricio F.")
        self.assertEqual(self.nc.numero_escalonamento, 2)

        info = self._escalate("Diretor")
        self.assertEqual(self.nc.numero_escalonamento, 2)
        self.assertIn("limite", info.call_args.args[2])

    def test_resolucao_pela_aba(self):
        def fake_exec(dialog):
            dialog.forma.setCurrentIndex(0)
            dialog.solucao.setPlainText("Arquivos renomeados.")
            dialog.evidencia.setPlainText("Baseline 1.2")
            return QDialog.DialogCode.Accepted

        with mock.patch.object(ResolverDialog, "exec", fake_exec), \
                mock.patch.object(nc_tab.QMessageBox, "question", return_value=NO):
            self.tab._resolve_nc()

        self.assertEqual(self.nc.status, STATUS_RESOLVIDA)
        self.assertEqual(self.nc.forma_resolucao, FORMAS_RESOLUCAO[0])
        self.assertIn("1 resolvidas", self.tab.summary.text())

    def test_envio_registra_comunicacao(self):
        self.tab._email_config.remetente = "qa@gmail.com"
        self.tab._email_config.servidor = "smtp.gmail.com"
        self.tab._smtp_password = "senha"
        with mock.patch.object(nc_tab, "send_message") as send, \
                mock.patch.object(nc_tab.QMessageBox, "information"):
            self.tab._send_email(self.nc, 0, [__file__])
        send.assert_called_once()
        self.assertEqual(len(self.nc.comunicacoes), 1)
        self.assertEqual(self.nc.comunicacoes[0]["destinatario"], "luis@example.com")

    def test_aviso_de_vencidas_separa_limite_atingido(self):
        with mock.patch.object(nc_tab.QMessageBox, "warning") as warning:
            self.tab._warn_overdue()
        self.assertIn("Devem ser escalonadas", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
