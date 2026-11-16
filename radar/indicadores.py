"""Indicadores de saúde por banco e trimestre (a partir do painel canônico)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def _q(anomes: pd.Series) -> pd.Series:
    return (anomes // 100) * 4 + (anomes % 100) // 3 - 1


def calcular(p: pd.DataFrame) -> pd.DataFrame:
    p = p.sort_values(["cod", "anomes"]).copy()
    g = p.groupby("cod", sort=False)
    q = _q(p["anomes"])

    def lag(col, n):
        x = g[col].shift(n)
        return x.where((q - g["anomes"].shift(n).pipe(_q)) == n)

    def ttm(col):
        s = sum(lag(col + "_tri", k) if k else p[col + "_tri"] for k in range(4))
        return s

    def media(col):
        return (p[col] + lag(col, 4)) / 2

    def cresc(col):
        ant = lag(col, 4)
        return (p[col] / ant - 1).where(ant > 0)

    def div(a, b):
        return (a / b).where(b.abs() > 0)

    p["carteira"] = p["credito_bruto"].fillna(p["carteira_credito"])
    i = pd.DataFrame({"cod": p["cod"], "anomes": p["anomes"]})
    for col in ("nome", "segmento", "situacao", "tcb"):
        if col in p:
            i[col] = p[col]
    i["ativo_total"] = p["ativo_total"]
    i["captacoes"] = p["captacoes"]
    i["carteira"] = p["carteira"]
    i["patrimonio_liquido"] = p["patrimonio_liquido"]

    # Capital
    i["basileia"] = p["basileia"]
    i["folga_basileia"] = p["basileia"] - C.BASILEIA_MINIMO
    i["indice_capital_principal"] = p["indice_capital_principal"]
    i["razao_alavancagem"] = p["razao_alavancagem"]
    i["delta_basileia_12m"] = p["basileia"] - lag("basileia", 4)
    i["pl_ativo"] = div(p["patrimonio_liquido"], p["ativo_total"])

    # Crescimento
    i["cresc_ativo_12m"] = cresc("ativo_total")
    i["cresc_captacoes_12m"] = cresc("captacoes")
    i["cresc_carteira_12m"] = cresc("carteira")
    i["cresc_dep_prazo_12m"] = cresc("depositos_prazo")
    i["captacoes_12m_atras"] = lag("captacoes", 4)
    i["ativo_12m_atras"] = lag("ativo_total", 4)
    i["gap_captacao_carteira"] = i["cresc_captacoes_12m"] - i["cresc_carteira_12m"]

    # Custo e rentabilidade (12 meses)
    desp = ttm("despesas_captacao")
    i["custo_captacao"] = div(desp.abs(), media("captacoes"))
    rend = ttm("rendas_credito")
    i["rend_carteira"] = div(rend, media("carteira"))
    i["cresc_rendas_credito_12m"] = div(rend, rend.groupby(p["cod"]).shift(4).where(
        (q - g["anomes"].shift(4).pipe(_q)) == 4)) - 1
    luc = ttm("lucro_liquido")
    i["lucro_12m"] = luc
    i["roe"] = div(luc, media("patrimonio_liquido").where(media("patrimonio_liquido") > 0))
    i["pdd_carteira"] = div(-ttm("resultado_pdd"), media("carteira"))
    i["rendas_tvm_ativo"] = div(ttm("rendas_tvm"), media("ativo_total"))

    # Inadimplência: carteira vencida há mais de 15 dias sobre a carteira de PF e PJ
    if "vencido_15d" in p:
        p["inadimplencia"] = div(p["vencido_15d"], p["carteira_pf_pj"])
        i["inadimplencia"] = p["inadimplencia"]
        i["delta_inadimplencia_12m"] = p["inadimplencia"] - lag("inadimplencia", 4)
    else:
        i["inadimplencia"] = np.nan
        i["delta_inadimplencia_12m"] = np.nan

    # Estrutura do balanço
    i["share_dep_prazo"] = div(p["depositos_prazo"], p["captacoes"])
    liq = p["disponibilidades"].fillna(0) + p["aplicacoes_interfinanceiras"].fillna(0)
    i["liquidez_imediata"] = div(liq, p["captacoes"])
    i["liquidez_ampla"] = div(liq + p["tvm"].fillna(0), p["captacoes"])
    conhecidos = sum(p[c].fillna(0) for c in (
        "disponibilidades", "aplicacoes_interfinanceiras", "tvm", "derivativos_ativo",
        "credito_liquido", "outras_op_credito", "arrendamento", "permanente"))
    residual = (p["ativo_total"] - conhecidos).clip(lower=0)
    i["share_ativos_outros"] = div(residual, p["ativo_total"])
    i["delta_ativos_outros_12m"] = i["share_ativos_outros"] - i.groupby("cod")["share_ativos_outros"].shift(4)
    return i.replace([np.inf, -np.inf], np.nan)
