"""Business rules from the course material (slides 3 and the QA plan)."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import tests  # noqa: F401  (starts the Qt application)
from models.nc_model import (
    CLASSIFICACAO_ADVERTENCIA,
    CLASSIFICACOES,
    FORMAS_RESOLUCAO,
    MAX_ESCALONAMENTOS,
    STATUS_ESCALONADA,
    STATUS_RESOLVIDA,
    NaoConformidade,
    classificacao_label,
    load_json,
    prazo_para,
    save_json,
)
from tests.helpers import make_nc


class ClassificacaoTests(unittest.TestCase):
    """R02/R03: severity table from 'Checklist de Processo e Produto'."""

    def test_tabela_oficial_do_checklist(self):
        esperado = {
            "Baixa-Simples": 4, "Baixa-Complexa": 5, "Baixa-Severa": 6,
            "Baixa-Extrema": 7, "Média-Simples": 3, "Média-Complexa": 4,
            "Média-Severa": 5, "Média-Extrema": 6, "Alta-Simples": 2,
            "Alta-Complexa": 3, "Alta-Severa": 4, "Alta-Extrema": 5,
            "Urgente-Simples": 1, "Urgente-Complexa": 2,
            "Urgente-Severa": 3, "Urgente-Extrema": 4,
        }
        for nome, dias in esperado.items():
            self.assertEqual(CLASSIFICACOES[nome], dias, nome)
        self.assertEqual(CLASSIFICACOES[CLASSIFICACAO_ADVERTENCIA], 0)

    def test_rotulo_igual_ao_exemplo_de_comunicacao(self):
        self.assertEqual(
            classificacao_label("Média-Simples"), "Média-Simples | 3 dias úteis"
        )
        self.assertEqual(
            classificacao_label("Urgente-Simples"), "Urgente-Simples | 1 dia útil"
        )
        self.assertEqual(
            classificacao_label("Advertência"), "Advertência | Não se aplica"
        )

    def test_prazo_do_exemplo_de_comunicacao(self):
        # Example: 1st request 16/03/2026, Média-Simples, deadline 19/03/2026.
        self.assertEqual(
            prazo_para("Média-Simples", date(2026, 3, 16)), date(2026, 3, 19)
        )

    def test_prazo_conta_apenas_dias_uteis(self):
        # Thursday + 3 business days skips the weekend.
        self.assertEqual(
            prazo_para("Média-Simples", date(2025, 11, 20)), date(2025, 11, 25)
        )
        # Friday + 1 business day lands on Monday.
        self.assertEqual(
            prazo_para("Urgente-Simples", date(2025, 11, 21)), date(2025, 11, 24)
        )


class AcompanhamentoTests(unittest.TestCase):
    """R01/R04: registration and follow-up until resolution."""

    def test_registro_tem_campos_minimos_da_acao_corretiva(self):
        nc = make_nc()
        # Slides: which NC, who resolves, deadline, NC type, solution.
        self.assertTrue(nc.descricao)
        self.assertTrue(nc.responsavel)
        self.assertEqual(nc.prazo, "2026-03-19")
        self.assertEqual(nc.classificacao, "Média-Simples")
        self.assertTrue(nc.acao_corretiva)

    def test_nc_vence_apos_prazo(self):
        nc = make_nc()
        self.assertFalse(nc.vencida(date(2026, 3, 19)))
        self.assertTrue(nc.vencida(date(2026, 3, 20)))

    def test_nc_resolvida_nunca_vence(self):
        nc = make_nc()
        nc.resolver(FORMAS_RESOLUCAO[0], "Arquivos renomeados.", "Baseline 1.2")
        self.assertFalse(nc.vencida(date(2030, 1, 1)))

    def test_advertencia_nao_tem_prazo_nem_vence(self):
        nc = make_nc(classificacao="Advertência", prazo="")
        self.assertEqual(nc.prazo_atual, "")
        self.assertFalse(nc.vencida(date(2030, 1, 1)))


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
        # Média-Simples = 3 business days from Friday 20/03 -> Wed 25/03.
        self.assertEqual(nc.prazo_atual, "2026-03-25")
        self.assertEqual(nc.prazo, "2026-03-19")  # original is kept
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
            "classificacao": "Média-Simples",
            "escalonamentos": [
                {"data": "2026-03-20T09:00", "superior": "GP", "prazo": "2026-03-25"}
            ],
        }
        nc = NaoConformidade.from_dict(antigo)
        self.assertEqual(nc.escalonamentos[0].email_superior, "")
        self.assertEqual(nc.comunicacoes, [])
        self.assertEqual(nc.solucao_adotada, "")


if __name__ == "__main__":
    unittest.main()
