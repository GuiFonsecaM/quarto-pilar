from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from radar import backtest, dossie, eventos, indicadores, noticias, painel, score


def _bruto(anomes, cod, linhas):
    return [{"AnoMes": anomes, "CodInst": cod, "NumeroRelatorio": rel, "Grupo": g, "Conta": "1",
             "NomeColuna": n, "Saldo": v} for rel, g, n, v in linhas]


def test_nucleo_ignora_acento_e_formula():
    assert painel.nucleo("Índice de Basileia  (n) = (e) / (j)") == "indice de basileia"
    assert painel.nucleo("Captações  (e) = (a) + (b)") == "captacoes"


def test_montar_e_trimestralizar():
    linhas = []
    for per, lucro in [(202503, 10.0), (202506, 25.0)]:
        linhas += _bruto(per, "C1", [
            ("1", None, "Ativo Total", 1000.0), ("1", None, "Índice de Basileia", 0.12),
            ("3", None, "Captações  (e) = (a) + (b)", 800.0), ("4", None, "Lucro Líquido  (z)", lucro),
            ("2", "Operações de Crédito", "Valor Contábil Bruto  (e1)", 500.0),
            ("2", "Operações de Crédito", "Operações de Crédito  (e)", 480.0),
        ])
    p = painel.montar(pd.DataFrame(linhas))
    assert list(p["ativo_total"]) == [1000.0, 1000.0]
    assert p["credito_bruto"].iloc[0] == 500.0 and p["credito_liquido"].iloc[0] == 480.0
    # junho acumula o semestre: lucro do 2º trimestre = 25 - 10
    assert p["lucro_liquido_tri"].tolist() == [10.0, 15.0]


def test_recebiveis_de_cartao_nao_contam_como_ativo_dificil():
    # Layout da Resolução 4.966: cartão/pós-pago tem linha própria (h) no relatório de Ativo
    grupo = "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago)"
    linhas = _bruto(202606, "C1", [
        ("1", None, "Ativo Total", 1000.0),
        ("2", None, "Disponibilidades \n(a)", 50.0),
        ("2", "Operações de Crédito", "Operações de Crédito \n(e)", 300.0),
        ("2", grupo, "Valor Contábil Bruto \n(h1)", 520.0),
        ("2", grupo, grupo + " \n(h)", 500.0),
        ("2", None, "Outros Ativos Realizáveis \n(i)", 150.0),
    ])
    p = painel.montar(pd.DataFrame(linhas))
    assert p["transacoes_pagamento"].iloc[0] == 500.0
    i = indicadores.calcular(p)
    assert abs(i["share_ativos_outros"].iloc[0] - 0.15) < 1e-9


def _indicadores_base(n=40):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "cod": [f"C{i}" for i in range(n)], "anomes": 202506, "nome": "X", "segmento": "S3", "tcb": "B1",
        "ativo_total": 5e9, "captacoes": 4e9, "captacoes_12m_atras": 2e9, "ativo_12m_atras": 4e9, "carteira": 2e9, "patrimonio_liquido": 5e8,
        "basileia": rng.uniform(0.14, 0.2, n), "folga_basileia": 0.05, "indice_capital_principal": 0.12,
        "razao_alavancagem": 0.08, "delta_basileia_12m": 0.0, "pl_ativo": 0.1, "cresc_ativo_12m": 0.1,
        "cresc_captacoes_12m": 0.1, "cresc_carteira_12m": 0.1, "cresc_dep_prazo_12m": 0.1,
        "gap_captacao_carteira": 0.0, "custo_captacao": rng.uniform(0.09, 0.11, n), "rend_carteira": 0.2,
        "cresc_rendas_credito_12m": 0.1, "lucro_12m": 1e8, "roe": 0.15, "pdd_carteira": 0.03,
        "rendas_tvm_ativo": 0.05, "share_dep_prazo": 0.4, "liquidez_imediata": rng.uniform(0.08, 0.12, n),
        "liquidez_ampla": 0.3, "share_ativos_outros": rng.uniform(0.1, 0.15, n), "delta_ativos_outros_12m": 0.0,
    })


def test_score_dispara_perfil_master():
    t = _indicadores_base()
    t.loc[0, ["basileia", "folga_basileia", "cresc_captacoes_12m", "gap_captacao_carteira", "custo_captacao",
              "share_dep_prazo", "liquidez_imediata", "share_ativos_outros"]] = \
        [0.11, 0.005, 0.9, 0.6, 0.17, 0.9, 0.01, 0.45]
    s = score.calcular(t)
    alvo = s[s["cod"] == "C0"].iloc[0]
    regras = {x["regra"] for x in alvo["sinais"]}
    assert {"capital_minimo", "captacao_acelerada", "captacao_cara", "ativos_dificeis"} <= regras
    assert alvo["score_dados"] >= 65 and alvo["nivel"] == "Alerta alto"
    assert s[s["cod"] != "C0"]["score_dados"].median() < 25


def test_classificacao_por_regras():
    assert eventos.classificar_regras("BC decreta liquidação extrajudicial do Banco X")[0] == "liquidacao_intervencao"
    assert eventos.classificar_regras("Banco Y vende carteira de crédito")[0] == "venda_ativos_carteiras"
    assert eventos.classificar_regras("Banco Z inaugura agência")[0] == "outro"


def test_score_noticias_decai_e_limita():
    agora = datetime.now(timezone.utc)
    ev = pd.DataFrame([
        {"cod": "C1", "tipo": "liquidacao_intervencao", "gravidade": 3, "status": "confirmado",
         "data": (agora - timedelta(days=1)).isoformat()},
        {"cod": "C1", "tipo": "investigacao_fraude", "gravidade": 3, "status": "confirmado",
         "data": (agora - timedelta(days=2)).isoformat()},
        {"cod": "C1", "tipo": "atraso_pagamento", "gravidade": 3, "status": "confirmado",
         "data": (agora - timedelta(days=2)).isoformat()},
        {"cod": "C1", "tipo": "problema_liquidez", "gravidade": 3, "status": "confirmado",
         "data": (agora - timedelta(days=3)).isoformat()},
        {"cod": "C2", "tipo": "multa_sancao", "gravidade": 2, "status": "rumor",
         "data": (agora - timedelta(days=100)).isoformat()},
    ])
    s = eventos.score_noticias(ev).set_index("cod")
    assert s.loc["C1", "score_noticias"] == 30      # limitado a 30
    assert "C2" not in s.index                      # fora da janela de 45 dias


def test_dossie_descarta_ponto_sem_evidencia():
    saida = {"resumo": "r", "pontos": [{"texto": "ok", "evidencias": ["F1"]},
                                       {"texto": "inventado", "evidencias": ["F99"]}]}
    v = dossie._validar(saida, {"F1", "N1"})
    assert [p["texto"] for p in v["pontos"]] == ["ok"]


def test_nome_exibicao():
    assert noticias.nome_exibicao("BANCO AFINZ BM - PRUDENCIAL") == "Banco Afinz"
    assert noticias.nome_exibicao("COOPERATIVA DE CRÉDITO X - SICOOB CREDICOPA") == "Sicoob Credicopa"


def test_publicacao_if_data():
    assert backtest.publicacao(202506).isoformat() == "2025-08-29"
    assert backtest.publicacao(202512).isoformat() == "2026-03-31"


def test_relacoes_ponto_de_vista_e_regras():
    from radar import relacoes
    bancos = pd.DataFrame({"cod": ["C1", "C2"], "nome_exibicao": ["Banco Alfa", "Banco Beta"],
                           "busca": ['"Banco Alfa"', '"Banco Beta"']})
    noticias_df = pd.DataFrame([{"id": "n1", "data": "2026-11-10T00:00:00+00:00", "titulo": "Banco Alfa vende carteira ao Banco Beta",
                                 "fonte": "X", "link": "https://x", "cod": "C1", "consulta": "", "origem": "",
                                 "coletado_em": "", "processado": False}])
    import radar.eventos as E
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        E.ARQ = pathlib.Path(d) / "ev.parquet"
        from radar import config as C
        C.DADOS = pathlib.Path(d)
        ev = E.processar(noticias_df, bancos, bancos)
    assert ev.iloc[0]["contraparte_cod"] == "C2" and ev.iloc[0]["relacao"] == "citado_junto"
    rel = relacoes.montar(ev, {"C1": "Banco Alfa", "C2": "Banco Beta"})
    beta = relacoes.do_banco(rel, "C2", {"C1", "C2"})
    assert any(r["outro_cod"] == "C1" and "Banco Alfa" in r["descricao"] for r in beta)
    master = relacoes.do_banco(rel, "C0080367", {"C0080367"})
    assert any("BRB" in r["outro"] for r in master)   # vem da lista verificada


def test_inadimplencia_mapeia_conglomerado_financeiro():
    cad = pd.DataFrame([{"AnoMes": 202412, "CodInst": "111", "CodConglomeradoFinanceiro": "C0050201",
                         "CodConglomeradoPrudencial": "C0080367"}])
    vals = pd.DataFrame([
        {"AnoMes": 202412, "CodInst": "C0050201", "NumeroRelatorio": "11", "TipoInstituicao": "2",
         "NomeColuna": "Vencido a Partir de 15 Dias", "Saldo": 5.0},
        {"AnoMes": 202412, "CodInst": "C0050201", "NumeroRelatorio": "11", "TipoInstituicao": "2",
         "NomeColuna": "Total da Carteira de Pessoa Física", "Saldo": 100.0},
        {"AnoMes": 202503, "CodInst": "C0080367", "NumeroRelatorio": "13", "TipoInstituicao": "1",
         "NomeColuna": "Total da Carteira de Pessoa Jurídica", "Saldo": 50.0},
    ])
    r = painel.inadimplencia(vals, cad).set_index("anomes")
    assert r.loc[202412, "cod"] == "C0080367" and r.loc[202412, "vencido_15d"] == 5.0
    assert r.loc[202503, "carteira_pf_pj"] == 50.0


def test_cdi_12m_acumula_doze_meses():
    from radar import cdbs
    mensal = {f"{a}-{m:02d}": 0.01 for a in (2025, 2026) for m in range(1, 13)}
    assert abs(cdbs.cdi_12m(202606, mensal) - (1.01 ** 12 - 1)) < 1e-9
    assert cdbs.cdi_12m(202506, {"2025-06": 0.01}) is None  # faltam meses: não inventa
