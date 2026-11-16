"""Transforma os relatórios brutos do IF.Data num painel canônico banco × trimestre.

Os nomes das colunas do IF.Data mudam ao longo do tempo (ex.: a Resolução 4.966
reorganizou Ativo e DRE em 2025). Por isso cada campo canônico tem uma lista de
candidatos, em ordem de preferência, comparados pelo "nome-núcleo" (sem acento,
minúsculo e sem o sufixo "(a) = ...").
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

# campo: [(relatorio, grupo-núcleo ou None, nome-núcleo), ...]
MAPA: dict[str, list[tuple[str, str | None, str]]] = {
    # Resumo / capital
    "ativo_total": [("1", None, "ativo total"), ("2", None, "ativo total")],
    "carteira_credito": [("1", None, "carteira de credito"), ("1", None, "carteira de credito classificada")],
    "captacoes": [("3", None, "captacoes"), ("1", None, "captacoes")],
    "patrimonio_liquido": [("1", None, "patrimonio liquido"), ("3", None, "patrimonio liquido")],
    "basileia": [("5", None, "indice de basileia"), ("1", None, "indice de basileia")],
    "indice_capital_principal": [("5", None, "indice de capital principal")],
    "indice_nivel1": [("5", None, "indice de capital nivel i")],
    "razao_alavancagem": [("5", None, "razao de alavancagem")],
    "imobilizacao": [("5", None, "indice de imobilizacao"), ("1", None, "indice de imobilizacao")],
    "capital_principal": [("5", None, "capital principal para comparacao com rwa")],
    "capital_complementar": [("5", None, "capital complementar")],
    "nivel2": [("5", None, "capital nivel ii")],
    "pr": [("5", None, "patrimonio de referencia para comparacao com o rwa"),
           ("1", None, "patrimonio de referencia para comparacao com o rwa")],
    "rwa": [("5", None, "ativos ponderados pelo risco")],
    "rwa_credito": [("5", None, "rwa para risco de credito")],
    "rwa_mercado": [("5", None, "rwa para risco de mercado")],
    "rwa_operacional": [("5", None, "rwa para risco operacional")],
    # Ativo
    "disponibilidades": [("2", None, "disponibilidades")],
    "aplicacoes_interfinanceiras": [("2", None, "aplicacoes interfinanceiras de liquidez")],
    "tvm": [("2", None, "tvm e instrumentos financeiros derivativos"), ("2", None, "titulos e valores mobiliarios")],
    "derivativos_ativo": [("2", None, "instrumentos derivativos")],
    "credito_bruto": [("2", "operacoes de credito", "valor contabil bruto"),
                      ("2", "operacoes de credito", "operacoes de credito")],
    "credito_liquido": [("2", "operacoes de credito", "operacoes de credito liquidas de provisao"),
                        ("2", "operacoes de credito", "operacoes de credito")],
    "outras_op_credito": [("2", None, "outras operacoes com caracteristicas de concessao de credito")],
    "arrendamento": [("2", None, "arrendamento mercantil liquido de provisao"),
                     ("2", None, "operacoes de arrendamento financeiro")],
    "outros_creditos": [("2", None, "outros creditos - liquido de provisao")],
    "outros_ativos_realizaveis": [("2", None, "outros ativos realizaveis")],
    "permanente": [("2", None, "permanente ajustado"), ("2", None, "ativo permanente")],
    # Passivo
    "depositos_vista": [("3", None, "depositos a vista")],
    "depositos_poupanca": [("3", None, "depositos de poupanca")],
    "depositos_interfinanceiros": [("3", None, "depositos interfinanceiros")],
    "depositos_prazo": [("3", None, "depositos a prazo")],
    "depositos_total": [("3", None, "deposito total"), ("3", None, "depositos")],
    "compromissadas": [("3", None, "obrigacoes por operacoes compromissadas")],
    "letras_financeiras": [("3", None, "letras financeiras")],
    "lci_lca": [("3", None, "letras de credito imobiliario")],  # somado com LCA abaixo
    "lca": [("3", None, "letras de credito do agronegocio")],
    # DRE (valores acumulados no semestre no IF.Data)
    "lucro_liquido": [("4", None, "lucro liquido"), ("1", None, "lucro liquido")],
    "rendas_credito": [("4", None, "rendas de operacoes de credito")],
    "rendas_tvm": [("4", None, "rendas de operacoes com tvm"), ("4", None, "rendas de titulos e valores mobiliarios")],
    "despesas_captacao": [("4", None, "despesas de captacao"), ("4", None, "despesas de captacoes")],
    "resultado_pdd": [("4", None, "resultado de provisao para creditos de dificil liquidacao"),
                      ("4", None, "resultado com perda esperada")],
    "resultado_intermediacao": [("4", None, "resultado de intermediacao financeira")],
    "despesas_pessoal": [("4", None, "despesas de pessoal")],
    "despesas_administrativas": [("4", None, "despesas administrativas")],
}

FLUXOS = ["lucro_liquido", "rendas_credito", "rendas_tvm", "despesas_captacao", "resultado_pdd",
          "resultado_intermediacao", "despesas_pessoal", "despesas_administrativas"]


def nucleo(txt) -> str:
    if txt is None or (isinstance(txt, float) and np.isnan(txt)):
        return ""
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    t = t.lower().strip()
    t = re.split(r"\s\(", t, maxsplit=1)[0]          # corta "(a) = ..."
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t


def _grupo_nucleo(g) -> str:
    n = nucleo(g)
    return n.split(" - ")[0] if n else ""


def montar(valores: pd.DataFrame, cadastro: pd.DataFrame | None = None) -> pd.DataFrame:
    """Devolve o painel wide: uma linha por (cod, anomes) e uma coluna por campo canônico."""
    if valores.empty:
        return pd.DataFrame()
    v = valores.copy()
    v["rel"] = v["NumeroRelatorio"].astype(str)
    v["nome_n"] = v["NomeColuna"].map(nucleo)
    v["grupo_n"] = v["Grupo"].map(_grupo_nucleo)
    v["Saldo"] = pd.to_numeric(v["Saldo"], errors="coerce")

    base = v.loc[v["rel"].isin(["1", "2", "3", "4", "5"]), ["CodInst", "AnoMes"]].drop_duplicates()
    out = base.set_index(["CodInst", "AnoMes"])
    for campo, cands in MAPA.items():
        serie = pd.Series(np.nan, index=out.index)
        for rel, grupo, nome in cands:
            m = (v["rel"] == rel) & (v["nome_n"] == nome)
            if grupo is not None:
                m &= v["grupo_n"] == grupo
            sub = v.loc[m].groupby(["CodInst", "AnoMes"])["Saldo"].first()
            if sub.empty:
                continue
            serie = serie.fillna(sub.reindex(out.index))
        out[campo] = serie
    out = out.reset_index().rename(columns={"CodInst": "cod", "AnoMes": "anomes"})
    out["anomes"] = out["anomes"].astype(int)
    out["lci_lca"] = out["lci_lca"].fillna(0) + out.pop("lca").fillna(0)
    inad = inadimplencia(valores, cadastro)
    if not inad.empty:
        out = out.merge(inad, on=["cod", "anomes"], how="left")
    else:
        out["vencido_15d"] = np.nan
        out["carteira_pf_pj"] = np.nan
    out = trimestralizar(out)
    if cadastro is not None and not cadastro.empty:
        out = anexar_cadastro(out, cadastro)
    return out.sort_values(["cod", "anomes"]).reset_index(drop=True)


def _mapa_financeiro(cad: pd.DataFrame) -> dict:
    """(anomes, código do conglomerado financeiro ou da instituição) -> código prudencial."""
    if cad is None or cad.empty or "CodConglomeradoFinanceiro" not in cad:
        return {}
    c = cad[cad["CodConglomeradoPrudencial"].astype(str).str.startswith("C")]
    mapa = {}
    fin = c[c["CodConglomeradoFinanceiro"].astype(str).str.startswith("C")]
    for (per, cf), g in fin.groupby(["AnoMes", "CodConglomeradoFinanceiro"]):
        mapa[(int(per), str(cf))] = g["CodConglomeradoPrudencial"].mode().iloc[0]
    for r in c[["AnoMes", "CodInst", "CodConglomeradoPrudencial"]].itertuples():
        mapa.setdefault((int(r.AnoMes), str(r.CodInst)), r.CodConglomeradoPrudencial)
    return mapa


def inadimplencia(valores: pd.DataFrame, cadastro: pd.DataFrame | None) -> pd.DataFrame:
    """Carteira vencida há mais de 15 dias (PF + PJ) por conglomerado prudencial.
    Até 2024 o BC publica esses relatórios por conglomerado financeiro, que é traduzido
    para o prudencial pelo cadastro."""
    v = valores[valores["NumeroRelatorio"].astype(str).isin(["11", "13"])].copy()
    if v.empty:
        return pd.DataFrame()
    nome = v["NomeColuna"].astype(str)
    v["venc"] = np.where(nome.str.startswith("Vencido a Partir de 15 Dias"), v["Saldo"], 0.0)
    v["tot"] = np.where(nome.str.startswith("Total da Carteira"), v["Saldo"], 0.0)
    g = v.groupby(["CodInst", "AnoMes", "TipoInstituicao"], as_index=False)[["venc", "tot"]].sum()
    mapa = _mapa_financeiro(cadastro)
    tipo2 = g["TipoInstituicao"].astype(str) == "2"
    g["cod"] = [mapa.get((int(a), str(c)), c) if t else c
                for c, a, t in zip(g["CodInst"], g["AnoMes"], tipo2)]
    g = g.groupby(["cod", "AnoMes"], as_index=False)[["venc", "tot"]].sum()
    g = g[g["tot"] > 0].rename(columns={"AnoMes": "anomes", "venc": "vencido_15d", "tot": "carteira_pf_pj"})
    g["anomes"] = g["anomes"].astype(int)
    return g


def trimestralizar(p: pd.DataFrame) -> pd.DataFrame:
    """Converte fluxos acumulados no semestre em valores do trimestre (sufixo _tri)."""
    p = p.sort_values(["cod", "anomes"]).copy()
    mes = p["anomes"] % 100
    for f in FLUXOS:
        ant = p.groupby("cod")[f].shift(1)
        ant_per = p.groupby("cod")["anomes"].shift(1)
        contiguo = (ant_per == p["anomes"] - 3)
        segundo_tri = mes.isin([6, 12])
        tri = p[f].where(~segundo_tri, p[f] - ant.where(contiguo))
        p[f + "_tri"] = tri
    return p


def anexar_cadastro(p: pd.DataFrame, cad: pd.DataFrame) -> pd.DataFrame:
    c = cad.rename(columns={"CodInst": "cod", "AnoMes": "anomes", "NomeInstituicao": "nome",
                            "Segmento": "segmento", "Situacao": "situacao", "Tcb": "tcb"})
    c = c[["cod", "anomes", "nome", "segmento", "situacao", "tcb"]]
    p = p.merge(c, on=["cod", "anomes"], how="left")
    # preenche nome/segmento com o último conhecido do banco
    for col in ("nome", "segmento", "tcb"):
        p[col] = p.groupby("cod")[col].transform(lambda s: s.ffill().bfill())
    p["nome"] = p["nome"].fillna(p["cod"])
    return p


def nome_curto(nome: str) -> str:
    n = re.sub(r"\s*-\s*PRUDENCIAL.*$", "", str(nome), flags=re.I).strip()
    return n.title().replace("S.A.", "").replace(" S/A", "").strip()
