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

COLS_VALORES = ["AnoMes", "CodInst", "NumeroRelatorio", "Grupo", "Conta", "NomeColuna", "Saldo"]
COLS_CADASTRO = ["AnoMes", "CodInst", "NomeInstituicao", "Segmento", "Situacao",
                 "CodConglomeradoPrudencial", "UF", "Tcb"]

# Mapeamento das colunas do arquivo de cadastro do portal (fallback REST)
REST_CADASTRO = {
    "c0": "CodInst", "c1": "Data", "c2": "NomeInstituicao", "c3": "Tcb", "c7": "UF",
    "c9": "Segmento", "c12": "CodConglomeradoPrudencial", "c17": "Situacao",
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


def baixar_valores(periodo: int, relatorio: str, s=None) -> pd.DataFrame:
    s = s or sessao()
    df = _paginar(s, C.OLINDA_VALORES, {
        "@AnoMes": str(periodo),
        "@TipoInstituicao": str(C.TIPO_PRUDENCIAL),
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
    df["CodInst"] = df["CodInst"].astype(str)
    df["Saldo"] = pd.to_numeric(df["Saldo"], errors="coerce")
    return df


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


def atualizar(completo: bool = False, refazer_ultimos: int = 2) -> list[int]:
    """Baixa o que falta. Devolve os períodos que ganharam dados novos."""
    s = sessao()
    if get(s, C.OLINDA + "/ListaDeRelatorio()", params={"$format": "json"}, tentativas=3) is None:
        log.error("API do IF.Data fora do ar ou inacessível. Mantendo os dados atuais.")
        return []
    periodos = trimestres()
    existentes = sorted({int(p.stem.split("_")[1]) for p in C.BRUTOS.glob("rel1_*.parquet")}) \
        if C.BRUTOS.exists() else []
    if completo or not existentes:
        alvo = periodos
    else:
        faltando = [p for p in periodos if p not in existentes]
        refazer = existentes[-refazer_ultimos:] if refazer_ultimos else []
        alvo = sorted(set(faltando) | set(refazer))

    novos = []
    for per in alvo:
        ok = False
        for rel in C.RELATORIOS:
            if rel == "5" and per < 201503:
                continue  # Informações de Capital só existem para prudenciais a partir de 2015
            df = baixar_valores(per, rel, s)
            if df.empty:
                log.info("Sem dados: relatório %s, %s", rel, per)
                continue
            df.to_parquet(_arq(f"rel{rel}_{per}.parquet"), index=False)
            ok = True
            log.info("Relatório %s, %s: %s linhas", rel, per, len(df))
        if ok:
            cad = baixar_cadastro(per, s)
            if not cad.empty:
                cad.to_parquet(_arq(f"cad_{per}.parquet"), index=False)
            novos.append(per)
    return novos


def carregar_brutos() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê todo o cache bruto (valores, cadastro)."""
    vals = [pd.read_parquet(p) for p in sorted(C.BRUTOS.glob("rel*_*.parquet"))]
    cads = [pd.read_parquet(p) for p in sorted(C.BRUTOS.glob("cad_*.parquet"))]
    v = pd.concat(vals, ignore_index=True) if vals else pd.DataFrame(columns=COLS_VALORES)
    c = pd.concat(cads, ignore_index=True) if cads else pd.DataFrame(columns=COLS_CADASTRO)
    return v, c
