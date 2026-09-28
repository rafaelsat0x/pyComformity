to execute (open) main window, run:

`.venv/bin/python -m ui.window`

A classificação de NC tem três opções: Simples (30 minutos), Média (45 minutos)
e Complexa (1 hora). A previsão de conclusão é calculada a partir da data e hora
da primeira solicitação e exibida como `dd/MM/aaaa HH:mm`.

Ao editar uma NC com classificação antiga, selecione uma das três opções.
Datas de arquivos antigos sem horário são interpretadas e exibidas como `00:00`.
