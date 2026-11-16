# Quarto Pilar

**Saúde dos bancos brasileiros em dados públicos.**

Site com atualização diária que procura **sinais de estresse financeiro em bancos brasileiros**. Ele cruza os balanços públicos do Banco Central (IF.Data) com notícias do dia e usa IA para apontar onde os números e as notícias **não condizem**. A ideia nasceu do caso Banco Master.

> Sinais estatísticos em dados públicos. Não é avaliação de crédito, acusação nem recomendação de investimento.

## Resultado do backtest (dados de 2014 a jun/2026)

| Instituição | Evento | 1º alerta | Antecedência |
|---|---|---|---|
| Banco Master | liquidação em 18/11/2025 | set/2022 | ~36 meses |
| BRK Financeira | liquidação em 2023 | mar/2022 | ~10 meses |
| Dacasa Financeira | liquidação em 2020 | mar/2015 | ~58 meses |
| Entrepay | liquidação em 2026 | dez/2025 | ~0 meses |

Detectou 4 de 4 quebras no universo monitorado. Entre as instituições que não quebraram, cerca de 5% ficaram em alerta. As regras foram calibradas conhecendo esses casos, então o resultado é otimista. O relatório completo fica em [`relatorios/backtest.md`](relatorios/backtest.md).

## Como funciona

```
IF.Data (BC) ──► painel banco × trimestre ──► indicadores ──► score de dados (0–100)
                                                                       │
Google Notícias + GDELT ──► IA (Groq) classifica eventos ──► score de notícias (0–30)
                                                                       │
                                     IA (Gemini) escreve dossiê com evidências ◄┘
                                                                       │
                                     site estático em docs/ (GitHub Pages)
```

- **Dados do BC**: relatórios Resumo, Ativo, Passivo, DRE e Informações de Capital, no nível do conglomerado prudencial.
- **Indicadores**: Basileia e folga até o mínimo, crescimento da captação e da carteira, custo de captação contra os pares, dependência de CDB, liquidez, ativos de difícil avaliação, coerência entre carteira e receita de crédito, ROE e alavancagem, além de anomalia multivariada (Isolation Forest).
- **IA sem custo**: Groq (leitura de manchetes) e Google Gemini (dossiês), nos planos gratuitos. Sem chave, o Quarto Pilar funciona só com regras fixas.
- **Antialucinação**: a IA só pode citar fatos (F1, F2…) e notícias (N1, N2…) fornecidos pelo sistema. Afirmações sem evidência válida são descartadas.

## Colocar no ar (tudo grátis)

1. Crie um repositório **público** no GitHub e envie este código.
2. Gere as chaves gratuitas:
   - Groq: https://console.groq.com/keys
   - Google AI Studio: https://aistudio.google.com/apikey
3. No repositório, em **Settings › Secrets and variables › Actions › New repository secret**, crie `GROQ_API_KEY` e `GEMINI_API_KEY`.
4. Em **Settings › Pages**, escolha *Deploy from a branch*, a branch `main` e a pasta `/docs`.
5. Em **Settings › Actions › General › Workflow permissions**, marque *Read and write permissions*.
6. Em **Actions**, rode manualmente **Carga inicial (histórico completo)**.
7. Agende a **Atualização diária** no [cron-job.org](https://cron-job.org) com um `POST` para
   `https://api.github.com/repos/GuiFonsecaM/quarto-pilar/actions/workflows/diario.yml/dispatches`,
   corpo `{"ref":"main"}` e os cabeçalhos `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`
   e `X-GitHub-Api-Version: 2022-11-28`. O token deve ser *fine-grained*, só deste repositório, com permissão **Actions: Read and write**.

## Rodar no computador

```bash
pip install -r requirements.txt
python -m radar carga-inicial   # baixa o histórico do IF.Data
python -m radar diario          # notícias, IA e site
python -m http.server -d docs   # abre o site em http://localhost:8000
pytest -q                       # testes
```

## Estrutura

```
radar/            código (coleta, painel, indicadores, score, backtest, notícias, IA, site)
config/           apelidos dos bancos para busca de notícias e eventos conhecidos
dados/            scores, notícias, eventos e dossiês (versionados)
docs/             site estático publicado no GitHub Pages
relatorios/       backtest em Markdown
.github/workflows atualização diária, carga inicial e testes
```

Criado por Guilherme Fonseca.
