"""Business rules from the course material (slides 3 and the QA plan)."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import tests  # noqa: F401  (starts the Qt application)
from models.nc_model import (
    CLASSIFICACOES,
    FORMAS_RESOLUCAO,
    MAX_ESCALONAMENTOS,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NaoConformidade,
    NcTableModel,
    classificacao_label,
    load_json,
    prazo_para,
    save_json,
)
from tests.helpers import make_nc


class ClassificacaoTests(unittest.TestCase):
    def test_tabela_de_gravidade(self):
        self.assertEqual(CLASSIFICACOES, {"Simples": 30, "Média": 45, "Complexa": 60})

    def test_rotulos_e_prazos(self):
        inicio = datetime(2026, 3, 20, 23, 40)
        for nome, minutos, rotulo in (
            ("Simples", 30, "Simples | 30 minutos"),
            ("Média", 45, "Média | 45 minutos"),
            ("Complexa", 60, "Complexa | 1 hora"),
        ):
            with self.subTest(nome=nome):
                self.assertEqual(classificacao_label(nome), rotulo)
                self.assertEqual(prazo_para(nome, inicio), inicio + timedelta(minutes=minutos))


class AcompanhamentoTests(unittest.TestCase):
    """R01/R04: registration and follow-up until resolution."""

    def test_registro_tem_campos_minimos_da_acao_corretiva(self):
        nc = make_nc()
        # Slides: which NC, who resolves, deadline, NC type, solution.
        self.assertTrue(nc.descricao)
        self.assertTrue(nc.responsavel)
        self.assertEqual(nc.prazo, "2026-03-16T09:45:00")
        self.assertEqual(nc.classificacao, "Média")
        self.assertTrue(nc.acao_corretiva)

    def test_nc_vence_apos_prazo(self):
        nc = make_nc()
        self.assertFalse(nc.vencida(datetime(2026, 3, 16, 9, 45)))
        self.assertTrue(nc.vencida(datetime(2026, 3, 16, 9, 45, 1)))

    def test_tabela_exibe_horario_em_todos_os_formatos_de_prazo(self):
        model = NcTableModel()
        coluna = next(i for i, (key, _) in enumerate(model.COLUMNS) if key == "prazo_atual")
        for prazo, esperado in (
            ("2026-03-16T09:45:00", "16/03/2026 09:45"),
            ("2026-03-16 09:45:00", "16/03/2026 09:45"),
            ("2026-03-16", "16/03/2026 00:00"),
            ("", ""),
        ):
            with self.subTest(prazo=prazo):
                model.set_items([make_nc(prazo=prazo)])
                self.assertEqual(model.data(model.index(0, coluna)), esperado)

    def test_nc_resolvida_nunca_vence(self):
        nc = make_nc()
        nc.resolver(FORMAS_RESOLUCAO[0], "Arquivos renomeados.", "Baseline 1.2")
        self.assertFalse(nc.vencida(datetime(2030, 1, 1)))

    def test_advertencia_nao_tem_prazo_nem_vence(self):
        nc = make_nc(classificacao="Advertência", prazo="")
        self.assertEqual(nc.prazo_atual, "")
        self.assertFalse(nc.vencida(datetime(2030, 1, 1)))


class EscalonamentoTests(unittest.TestCase):
    """R05/R06/R07: escalation process from slide 'ESCALONAMENTO'."""

    def test_escalona_para_superior_com_novo_prazo_do_tempo_original(self):
        nc = make_nc()
        nc.escalonar(
            "Gerente de Projeto",
            "Prazo expirado.",
            "gp@example.com",
            quando=datetime(2026, 3, 20, 9, 0),  # Friday
        )
        self.assertEqual(nc.status, STATUS_ESCALONADA)
        self.assertEqual(nc.numero_escalonamento, 1)
        # Média = 45 minutes from the escalation time.
        self.assertEqual(nc.prazo_atual, "2026-03-20T09:45:00")
        self.assertEqual(nc.prazo, "2026-03-16T09:45:00")  # original is kept
        self.assertEqual(nc.escalonamentos[0].superior, "Gerente de Projeto")

    def test_responsavel_nao_muda_apos_escalonar(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", quando=datetime(2026, 3, 20))
        self.assertEqual(nc.responsavel, "Luis S")

    def test_limite_de_dois_niveis(self):
        nc = make_nc()
        nc.escalonar("Gerente de Projeto", quando=datetime(2026, 3, 20))
        nc.escalonar("Mauricio F.", quando=datetime(2026, 3, 26))
        self.assertEqual(nc.numero_escalonamento, MAX_ESCALONAMENTOS)
        self.assertTrue(nc.limite_escalonamento_atingido)
        with self.assertRaises(ValueError):
            nc.escalonar("Diretor", quando=datetime(2026, 4, 1))

    def test_nao_escalona_resolvida_nem_advertencia(self):
        resolvida = make_nc()
        resolvida.resolver(FORMAS_RESOLUCAO[0], "ok", "ok")
        with self.assertRaises(ValueError):
            resolvida.escalonar("Gerente")

        advertencia = make_nc(classificacao="Advertência", prazo="")
        with self.assertRaises(ValueError):
            advertencia.escalonar("Gerente")

    def test_superior_obrigatorio(self):
        with self.assertRaises(ValueError):
            make_nc().escalonar("   ")

    def test_classificacao_antiga_pede_atualizacao_antes_de_escalonar(self):
        nc = make_nc(classificacao="Média-Simples", prazo="2026-03-19")
        with self.assertRaisesRegex(ValueError, "classificação válida"):
            nc.escalonar("Gerente")
        self.assertEqual(nc.escalonamentos, [])

    def test_destinatarios_incluem_superior_apos_escalonar(self):
        nc = make_nc()
        self.assertEqual(nc.destinatarios(), ["luis@example.com"])
        nc.escalonar("Gerente", email_superior="gp@example.com")
        self.assertEqual(
            nc.destinatarios(), ["luis@example.com", "gp@example.com"]
        )


class ResolucaoTests(unittest.TestCase):
    """R10: resolution registered with solution and proof."""

    def test_resolucao_registra_solucao_comprovacao_e_data(self):
        nc = make_nc()
        nc.resolver(
            FORMAS_RESOLUCAO[0],
            "Arquivos renomeados conforme padrão.",
            "Baseline 1.2 conferida pelo QA.",
            quando=datetime(2026, 3, 18, 14, 30),
        )
        self.assertEqual(nc.status, STATUS_RESOLVIDA)
        self.assertEqual(nc.conclusao_em, "2026-03-18T14:30")
        self.assertEqual(nc.solucao_adotada, "Arquivos renomeados conforme padrão.")
        self.assertEqual(nc.evidencia_resolucao, "Baseline 1.2 conferida pelo QA.")

    def test_as_tres_formas_de_resolver_do_slide(self):
        self.assertEqual(len(FORMAS_RESOLUCAO), 3)
        self.assertIn("exceção", FORMAS_RESOLUCAO[2])
        nc = make_nc()
        nc.resolver(FORMAS_RESOLUCAO[2], "Decisão da diretoria.", "Ata 12/2026")
        self.assertEqual(nc.forma_resolucao, FORMAS_RESOLUCAO[2])

    def test_resolucao_exige_solucao_e_comprovacao(self):
        nc = make_nc()
        with self.assertRaises(ValueError):
            nc.resolver(FORMAS_RESOLUCAO[0], "", "ok")
        with self.assertRaises(ValueError):
            nc.resolver(FORMAS_RESOLUCAO[0], "ok", "  ")
        with self.assertRaises(ValueError):
            nc.resolver("qualquer coisa", "ok", "ok")


class PersistenciaTests(unittest.TestCase):
    """R11: NC register survives save/open, including older files."""

    def test_json_ida_e_volta(self):
        nc = make_nc()
        nc.escalonar("Gerente", "Prazo expirado.", "gp@example.com")
        nc.registrar_comunicacao("luis@example.com", "nc.pdf")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ncs.json"
            save_json(path, [nc])
            self.assertEqual(load_json(path), [nc])

    def test_arquivo_antigo_sem_campos_novos_abre(self):
        antigo = {
            "id": 7,
            "descricao": "x",
            "classificacao": "Média",
            "escalonamentos": [
                {"data": "2026-03-20T09:00", "superior": "GP", "prazo": "2026-03-20T09:45:00"}
            ],
        }
        nc = NaoConformidade.from_dict(antigo)
        self.assertEqual(nc.escalonamentos[0].email_superior, "")
        self.assertEqual(nc.comunicacoes, [])
        self.assertEqual(nc.solucao_adotada, "")


if __name__ == "__main__":
    unittest.main()
