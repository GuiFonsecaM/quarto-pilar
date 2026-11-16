"""Motor de sinais: compara cada banco com seus pares e gera um score de alerta (0–100).

Cada regra devolve pontos e uma frase com a evidência numérica. O score usa apenas
dados até o próprio trimestre (sem olhar o futuro), o que permite o backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from . import config as C

NIVEIS = [(65, "Alerta alto"), (45, "Alerta"), (25, "Atenção"), (0, "Normal")]

FEATURES_ANOMALIA = ["folga_basileia", "cresc_ativo_12m", "cresc_captacoes_12m", "gap_captacao_carteira",
                     "custo_rel", "share_dep_prazo", "liquidez_imediata", "share_ativos_outros", "roe",
                     "rend_rel", "pl_ativo"]


def nivel(score: float) -> str:
    for lim, nome in NIVEIS:
        if score >= lim:
            return nome
    return "Normal"


def _pct(x):
    return f"{x * 100:.1f}%".replace(".", ",")


def _pp(x):
    return f"{x * 100:.1f} p.p.".replace(".", ",", 1)


def _grupo_pares(df: pd.DataFrame) -> pd.Series:
    seg = df["segmento"].astype(str).where(df["segmento"].astype(str).str.match(r"S[1-5]$"))
    # sem segmento: agrupa por porte
    porte = pd.cut(df["ativo_total"], [0, 5e9, 50e9, 300e9, np.inf], labels=["S5", "S4", "S3", "S2"])
    return seg.fillna(porte.astype(str))


def _robusto(x: pd.Series, grupo: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Mediana dos pares e z-score robusto (mediana/MAD) dentro do grupo."""
    med = x.groupby(grupo).transform("median")
    mad = (x - med).abs().groupby(grupo).transform("median") * 1.4826
    n = x.groupby(grupo).transform("count")
    med_all = x.median()
    mad_all = (x - med_all).abs().median() * 1.4826
    med = med.where(n >= 8, med_all)
    mad = mad.where(n >= 8, mad_all).replace(0, np.nan)
    return med, (x - med) / mad


def pontuar_trimestre(t: pd.DataFrame) -> pd.DataFrame:
    """Recebe os indicadores de um trimestre (universo monitorado) e devolve pontos e sinais."""
    t = t.copy()
    t["grupo"] = _grupo_pares(t)
    med_custo, _ = _robusto(t["custo_captacao"], t["grupo"])
    med_rend, _ = _robusto(t["rend_carteira"], t["grupo"])
    _, z_liq = _robusto(t["liquidez_imediata"], t["grupo"])
    t["custo_rel"] = t["custo_captacao"] / med_custo
    t["rend_rel"] = t["rend_carteira"] / med_rend
    _, z_outros = _robusto(t["share_ativos_outros"], t["grupo"])
    if "inadimplencia" not in t:
        t["inadimplencia"] = np.nan
        t["delta_inadimplencia_12m"] = np.nan
    med_inad, _ = _robusto(t["inadimplencia"], t["grupo"])
    t["inad_rel"] = t["inadimplencia"] / med_inad.replace(0, np.nan)

    # anomalia multivariada
    t["anomalia"] = False
    X = t[FEATURES_ANOMALIA].copy()
    ok = X.notna().sum(axis=1) >= len(FEATURES_ANOMALIA) - 2
    if ok.sum() >= 30:
        Xo = X[ok].clip(X[ok].quantile(0.01), X[ok].quantile(0.99), axis=1)
        Xo = (Xo - Xo.median()) / (Xo.std() + 1e-9)
        Xo = Xo.fillna(0)
        modelo = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
        t.loc[ok, "anomalia"] = modelo.fit_predict(Xo) == -1

    pontos, sinais = [], []
    for _, r in t.iterrows():
        pts, ss = 0, []

        def add(n, cod, texto, valor=None):
            nonlocal pts
            pts += n
            ss.append({"regra": cod, "pontos": n, "texto": texto, "valor": valor})

        b = r["folga_basileia"]
        if pd.isna(b) and r.get("basileia_antes", False):
            add(10, "capital_nao_divulgado", "Índice de Basileia não divulgado neste trimestre (era divulgado antes)")
        if pd.notna(b):
            if b < 0:
                add(25, "capital_abaixo_minimo", f"Basileia de {_pct(r['basileia'])}, abaixo do mínimo de 10,5%", r["basileia"])
            elif b < 0.01:
                add(20, "capital_minimo", f"Basileia de {_pct(r['basileia'])}, a menos de 1 p.p. do mínimo de 10,5%", r["basileia"])
            elif b < 0.025:
                add(10, "capital_baixo", f"Basileia de {_pct(r['basileia'])}, perto do mínimo de 10,5%", r["basileia"])
        # queda só preocupa se o capital já não estiver muito acima do mínimo
        if pd.notna(r["delta_basileia_12m"]) and r["delta_basileia_12m"] < -0.02 and pd.notna(b) and b < 0.08:
            add(8, "capital_caindo", f"Basileia caiu {_pp(-r['delta_basileia_12m'])} em 12 meses", r["delta_basileia_12m"])

        # crescimento sobre base pequena (menos de R$ 500 mi há 12 meses) distorce o percentual
        base_ok = pd.notna(r.get("captacoes_12m_atras")) and r["captacoes_12m_atras"] >= 5e8
        cc = r["cresc_captacoes_12m"] if base_ok else np.nan
        if pd.notna(cc) and cc > 0.5:
            add(18 if cc > 1 else 12, "captacao_acelerada", f"Captação cresceu {_pct(cc)} em 12 meses", cc)
        gap = r["gap_captacao_carteira"]
        if pd.notna(gap) and gap > 0.3 and pd.notna(cc) and cc > 0.2:
            add(10, "captacao_sem_credito",
                f"Captação cresceu {_pp(gap)} a mais que a carteira de crédito em 12 meses", gap)
        cr = r["custo_rel"]
        if pd.notna(cr) and cr > 1.25 and pd.notna(r["custo_captacao"]):
            add(15 if cr > 1.5 else 10, "captacao_cara",
                f"Custo de captação de {_pct(r['custo_captacao'])} ao ano, " + f"{cr:.1f}".replace(".", ",") + "x a mediana dos pares", cr)
        sp = r["share_dep_prazo"]
        if pd.notna(sp) and sp > 0.7:
            add(6, "dependencia_cdb", f"{_pct(sp)} da captação vem de depósitos a prazo (CDB)", sp)
        zl = z_liq.get(r.name, np.nan)
        li = r["liquidez_imediata"]
        if pd.notna(li) and ((pd.notna(zl) and zl < -1.5) or (li < 0.02 and pd.notna(sp) and sp > 0.5)):
            add(8, "liquidez_baixa", f"Liquidez imediata de {_pct(r['liquidez_imediata'])} da captação, bem abaixo dos pares", r["liquidez_imediata"])
        so = r["share_ativos_outros"]
        zo = z_outros.get(r.name, np.nan)
        if pd.notna(so) and so > 0.3 and pd.notna(zo) and zo > 2:
            add(12, "ativos_dificeis", f"{_pct(so)} do ativo fora de caixa, títulos e crédito (ativos de difícil avaliação)", so)
            if pd.notna(r["delta_ativos_outros_12m"]) and r["delta_ativos_outros_12m"] > 0.05:
                add(5, "ativos_dificeis_subindo", f"Essa fatia subiu {_pp(r['delta_ativos_outros_12m'])} em 12 meses", r["delta_ativos_outros_12m"])
        ck, cre = r["cresc_carteira_12m"], r["cresc_rendas_credito_12m"]
        if pd.notna(ck) and pd.notna(cre) and ck > 0.3 and cre < ck / 2:
            add(10, "credito_sem_receita",
                f"Carteira cresceu {_pct(ck)}, mas a receita de crédito só {_pct(cre)} — não condiz", ck - cre)
        elif pd.notna(r["rend_rel"]) and r["rend_rel"] < 0.5 and pd.notna(r["carteira"]) and r["carteira"] > 0.2 * r["ativo_total"]:
            add(8, "credito_rende_pouco", f"Carteira rende {r['rend_rel']:.1f}x a mediana dos pares".replace(".", ","), r["rend_rel"])
        roe = r["roe"]
        if pd.notna(roe) and roe < 0:
            add(12 if roe < -0.1 else 8, "prejuizo", f"Prejuízo em 12 meses (ROE de {_pct(roe)})", roe)
        ca = r["cresc_ativo_12m"] if pd.notna(r.get("ativo_12m_atras")) and r["ativo_12m_atras"] >= 1e9 else np.nan
        if pd.notna(ca) and ca > 0.6:
            add(8, "ativo_explosivo", f"Ativo total cresceu {_pct(ca)} em 12 meses", ca)
        ina, inr = r["inadimplencia"], r["inad_rel"]
        if pd.notna(ina) and pd.notna(inr) and ina > 0.08 and inr > 2.5:
            add(12 if inr > 4 else 8, "inadimplencia_alta",
                f"Inadimplência de {_pct(ina)} da carteira, " + f"{inr:.1f}".replace(".", ",") + "x a mediana dos pares", ina)
        if pd.notna(r["delta_inadimplencia_12m"]) and r["delta_inadimplencia_12m"] > 0.03 and pd.notna(ina) and ina > 0.06:
            add(5, "inadimplencia_subindo", f"Inadimplência subiu {_pp(r['delta_inadimplencia_12m'])} em 12 meses", r["delta_inadimplencia_12m"])
        if pd.notna(r["pl_ativo"]) and r["pl_ativo"] < 0.06:
            add(6, "alavancagem", f"Patrimônio líquido de apenas {_pct(r['pl_ativo'])} do ativo", r["pl_ativo"])
        if r["anomalia"]:
            add(8, "anomalia", "Combinação de indicadores atípica em relação a todo o sistema")
        pontos.append(min(100, pts))
        sinais.append(sorted(ss, key=lambda s: -s["pontos"]))
    t["score_dados"] = pontos
    t["sinais"] = sinais
    return t


def calcular(ind: pd.DataFrame) -> pd.DataFrame:
    """Score para todos os trimestres do universo monitorado."""
    ind = ind.sort_values(["cod", "anomes"]).copy()
    ind["basileia_antes"] = ind.groupby("cod")["basileia"].transform(
        lambda x: x.notna().shift(1).rolling(4, min_periods=1).max()).fillna(0).astype(bool)
    u = ind[ind["ativo_total"] >= C.ATIVO_MINIMO]
    if "tcb" in u:
        u = u[u["tcb"].isin(C.UNIVERSO_TCB) | u["tcb"].isna()]
    partes = [pontuar_trimestre(t) for _, t in u.groupby("anomes")]
    s = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if not s.empty:
        s["nivel"] = s["score_dados"].map(nivel)
    return s
