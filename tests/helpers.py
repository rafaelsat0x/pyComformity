from datetime import date

from models.nc_model import NaoConformidade, prazo_para


def make_nc(**overrides):
    """NC based on the course's communication example."""
    data = {
        "id": 1,
        "projeto": "Projeto Exemplo",
        "descricao": (
            "Os itens de configuração seguem o padrão de nomenclatura de "
            "arquivos conforme estabelecido nas Regras de Gerência de "
            "Configuração?"
        ),
        "classificacao": "Média-Simples",
        "acao_corretiva": (
            "Corrigir nomenclatura dos Itens de Configuração conforme "
            "estabelecido nas Regras de Gerência de Configuração."
        ),
        "responsavel": "Luis S",
        "email_responsavel": "luis@example.com",
        "responsavel_qa": "Vinicius",
        "data_solicitacao": "2026-03-16",
        "observacoes": (
            "O relatório de não conformidade de testes deve seguir as regras "
            "de gerência de configuração."
        ),
    }
    data.update(overrides)
    nc = NaoConformidade(**data)
    if "prazo" not in overrides:
        nc.prazo = prazo_para(
            nc.classificacao, date.fromisoformat(nc.data_solicitacao)
        ).isoformat()
    return nc
