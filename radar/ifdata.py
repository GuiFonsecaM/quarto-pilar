"""Coleta do IF.Data (Banco Central) — relatórios trimestrais e cadastro.

Os dados brutos ficam em dados/brutos/ (cache local, fora do git):
    rel{R}_{AAAAMM}.parquet   valores do relatório R para conglomerados prudenciais
    cad_{AAAAMM}.parquet      cadastro de instituições e conglomerados
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from . import config as C
from .http import get, sessao

log = logging.getLogger("radar.ifdata")

COLS_VALORES = ["AnoMes", "CodInst", "NumeroRelatorio", "Grupo", "Conta", "NomeColuna", "Saldo", "TipoInstituicao"]
COLS_CADASTRO = ["AnoMes", "CodInst", "NomeInstituicao", "Segmento", "Situacao",
                 "CodConglomeradoPrudencial", "CodConglomeradoFinanceiro", "UF", "Tcb"]

# Carteira de crédito por modalidade e prazo (traz o "vencido a partir de 15 dias"):
# 11 = pessoa física, 13 = pessoa jurídica. Até dez/2024 o BC publica só para conglomerados
# financeiros (tipo 2); a partir de mar/2025, para conglomerados prudenciais (tipo 1).
RELATORIOS_CREDITO = {"11": "Carteira PF por modalidade e prazo", "13": "Carteira PJ por modalidade e prazo"}
INICIO_CREDITO = 201406

# Mapeamento das colunas do arquivo de cadastro do portal (fallback REST)
REST_CADASTRO = {
    "c0": "CodInst", "c1": "Data", "c2": "NomeInstituicao", "c3": "Tcb", "c7": "UF",
    "c9": "Segmento", "c11": "CodConglomeradoFinanceiro", "c12": "CodConglomeradoPrudencial", "c17": "Situacao",
}


def trimestres(inicio: int = C.ANO_INICIAL, ate: date | None = None) -> list[int]:
    """Datas-base trimestrais (AAAAMM) já fechadas há pelo menos 55 dias."""
    hoje = ate or date.today()
    out = []
    for ano in range(inicio, hoje.year + 1):
        for mes in (3, 6, 9, 12):
            fim = date(ano, mes, 28)
            if (hoje - fim).days >= 55:
                out.append(ano * 100 + mes)
    return out


def _paginar(s, url: str, params: dict, top: int = 10000) -> pd.DataFrame:
    partes, skip = [], 0
    while True:
        p = dict(params, **{"$top": top, "$skip": skip})
        r = get(s, url, params=p, headers={"Accept": "application/json;odata.metadata=minimal"})
        if r is None:
            break
        try:
            linhas = r.json().get("value", [])
        except ValueError:
            break
        if not linhas:
            break
        partes.append(pd.DataFrame(linhas))
        if len(linhas) < top:
            break
        skip += len(linhas)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def baixar_valores(periodo: int, relatorio: str, s=None, tipo: int = C.TIPO_PRUDENCIAL) -> pd.DataFrame:
    s = s or sessao()
    df = _paginar(s, C.OLINDA_VALORES, {
        "@AnoMes": str(periodo),
        "@TipoInstituicao": str(tipo),
        "@Relatorio": f"'{relatorio}'",
        "$format": "json",
    })
    if df.empty:
        return df
    for c in COLS_VALORES:
        if c not in df.columns:
            df[c] = None
    df = df[COLS_VALORES].copy()
    df["AnoMes"] = int(periodo)
    df["NumeroRelatorio"] = str(relatorio)
    df["TipoInstituicao"] = str(tipo)
    df["CodInst"] = df["CodInst"].astype(str)
    df["Saldo"] = pd.to_numeric(df["Saldo"], errors="coerce")
    if relatorio in RELATORIOS_CREDITO:  # só o que o radar usa, para o cache não crescer à toa
        df = df[df["NomeColuna"].astype(str).str.contains("Vencido a Partir de 15 Dias|Total da Carteira", regex=True)]
    return df


def esperados(periodo: int) -> list[tuple[str, int]]:
    """Relatórios (e tipo de instituição) que devem existir para um período."""
    out = [(r, C.TIPO_PRUDENCIAL) for r in C.RELATORIOS if not (r == "5" and periodo < 201503)]
    if periodo >= INICIO_CREDITO:
        tipo = C.TIPO_PRUDENCIAL if periodo >= 202503 else 2
        out += [(r, tipo) for r in RELATORIOS_CREDITO]
    return out


def baixar_cadastro(periodo: int, s=None) -> pd.DataFrame:
    """Cadastro de um período: tenta a API Olinda e, se falhar, o arquivo do portal."""
    s = s or sessao()
    df = _paginar(s, C.OLINDA_CADASTRO, {"@AnoMes": str(periodo), "$format": "json"}, top=5000)
    if df.empty:
        partes = []
        for tipo in (1009, 1006):  # 1009 = conglomerados prudenciais, 1006 = instituições
            pref = f"ifdata_2025_2030/{periodo}" if periodo >= 202500 else str(periodo)
            r = get(s, C.IFDATA_REST, params={"nomeArquivo": f"{pref}/cadastro{periodo}_{tipo}.json"},
                    headers={"Referer": "https://www3.bcb.gov.br/ifdata/"})
            if r is not None and len(r.text) > 100:
                try:
                    partes.append(pd.DataFrame(r.json()).rename(columns=REST_CADASTRO))
                except ValueError:
                    pass
        df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if df.empty:
        return df
    if "Segmento" in df.columns and "Sr" in df.columns:
        # Para conglomerados, o segmento prudencial (S1..S5) vem em "Sr"
        df["Segmento"] = df["Sr"].where(df["Sr"].astype(str).str.match(r"S\d"), df["Segmento"])
    for c in COLS_CADASTRO:
        if c not in df.columns:
            df[c] = None
    df = df[COLS_CADASTRO].copy()
    df["AnoMes"] = int(periodo)
    df["CodInst"] = df["CodInst"].astype(str)
    return df.drop_duplicates(["AnoMes", "CodInst"])


def _arq(nome: str):
    C.BRUTOS.mkdir(parents=True, exist_ok=True)
    return C.BRUTOS / nome


def _tem(nome: str, coluna: str | None = None) -> bool:
    p = C.BRUTOS / nome
    if not p.exists():
        return False
    if coluna is None:
        return True
    import pyarrow.parquet as pq
    return coluna in pq.read_schema(p).names


def atualizar(completo: bool = False, refazer_ultimos: int = 2) -> list[int]:
    """Baixa o que falta (relatórios novos, períodos novos ou cadastro incompleto).
    Devolve os períodos que ganharam dados novos."""
    s = sessao()
    if get(s, C.OLINDA + "/ListaDeRelatorio()", params={"$format": "json"}, tentativas=3) is None:
        log.error("API do IF.Data fora do ar ou inacessível. Mantendo os dados atuais.")
        return []
    periodos = trimestres()
    recentes = set(periodos[-refazer_ultimos:]) if refazer_ultimos else set()
    hoje = date.today()
    novos = []
    for per in periodos:
        ok = False
        for rel, tipo in esperados(per):
            nome = f"rel{rel}_{per}.parquet"
            if _tem(nome) and not completo and per not in recentes:
                continue
            df = baixar_valores(per, rel, s, tipo)
            if df.empty:
                log.info("Sem dados: relatório %s, %s", rel, per)
                # período antigo sem dados: grava vazio para não tentar de novo todo dia
                if (hoje - date(per // 100, per % 100, 28)).days > 200:
                    pd.DataFrame(columns=COLS_VALORES).to_parquet(_arq(nome), index=False)
                continue
            df.to_parquet(_arq(nome), index=False)
            ok = True
            log.info("Relatório %s (tipo %s), %s: %s linhas", rel, tipo, per, len(df))
        cad = f"cad_{per}.parquet"
        if ok or not _tem(cad, "CodConglomeradoFinanceiro"):
            c = baixar_cadastro(per, s)
            if not c.empty:
                c.to_parquet(_arq(cad), index=False)
        if ok:
            novos.append(per)
    return novos


def carregar_brutos() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê todo o cache bruto (valores, cadastro)."""
    vals = [pd.read_parquet(p) for p in sorted(C.BRUTOS.glob("rel*_*.parquet"))]
    cads = [pd.read_parquet(p) for p in sorted(C.BRUTOS.glob("cad_*.parquet"))]
    v = pd.concat(vals, ignore_index=True) if vals else pd.DataFrame(columns=COLS_VALORES)
    c = pd.concat(cads, ignore_index=True) if cads else pd.DataFrame(columns=COLS_CADASTRO)
    return v, c
