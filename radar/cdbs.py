"""Página de CDBs: quanto cada banco paga para captar, comparado ao CDI e aos pares.

O CDI vem da série 4391 do SGS (Banco Central): CDI acumulado no mês, em % ao mês.
Sem acesso ao SGS, a página mostra só a comparação com os pares.
"""
from __future__ import annotations

import json
import logging
from datetime import date

import pandas as pd

from . import config as C
from .http import get, sessao

log = logging.getLogger("radar.cdbs")

ARQ_CDI = C.DADOS / "cdi_mensal.json"
SGS_CDI_MES = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados"

# Regras do score ligadas a quem compra CDB do banco
REGRAS_CDB = ("captacao_cara", "captacao_acelerada", "captacao_sem_credito", "dependencia_cdb",
              "liquidez_baixa", "capital_abaixo_minimo", "capital_minimo", "capital_baixo",
              "capital_nao_divulgado", "capital_caindo")

FGC_POR_CONGLOMERADO = 250_000
FGC_TETO_4_ANOS = 1_000_000
_MEMO: dict | None = None


def _cdi_mensal() -> dict[str, float]:
    """{'AAAA-MM': taxa do mês em fração}. Uma consulta por rodada; se falhar, usa o cache."""
    global _MEMO
    if _MEMO is not None:
        return _MEMO
    cache = json.loads(ARQ_CDI.read_text(encoding="utf-8")) if ARQ_CDI.exists() else {}
    _MEMO = cache
    hoje = date.today()
    mes_atual = f"{hoje.year}-{hoje.month:02d}"
    inicio = "01/01/2013"
    r = get(sessao(), SGS_CDI_MES, params={"formato": "json", "dataInicial": inicio,
                                           "dataFinal": hoje.strftime("%d/%m/%Y")}, tentativas=3)
    if r is None:
        log.warning("SGS (CDI) inacessível; usando o que estiver em cache.")
        return cache
    try:
        for x in r.json():
            d, m, a = x["data"].split("/")
            v = float(str(x["valor"]).replace(",", ".")) / 100
            if 0 < v < 0.05 and f"{a}-{m}" != mes_atual:  # mês corrente ainda incompleto
                cache[f"{a}-{m}"] = v
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Resposta inesperada do SGS: %s", e)
        return cache
    ARQ_CDI.parent.mkdir(parents=True, exist_ok=True)
    ARQ_CDI.write_text(json.dumps(dict(sorted(cache.items()))), encoding="utf-8")
    return cache


def cdi_12m(anomes: int, mensal: dict[str, float] | None = None) -> float | None:
    """CDI acumulado nos 12 meses que terminam no mês do balanço (AAAAMM)."""
    mensal = _cdi_mensal() if mensal is None else mensal
    a, m = divmod(int(anomes), 100)
    fator = 1.0
    for _ in range(12):
        v = mensal.get(f"{a}-{m:02d}")
        if v is None:
            return None
        fator *= 1 + v
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return fator - 1


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else round(f, 6)


def montar(atual: pd.DataFrame, nomes: dict, liquidadas: set, tipos: dict) -> dict:
    mensal = _cdi_mensal()
    ref = int(atual["anomes"].max())
    cdi_ref = cdi_12m(ref, mensal)
    bancos = []
    for _, l in atual.iterrows():
        custo = _num(l.get("custo_captacao"))
        cdi_b = cdi_12m(int(l["anomes"]), mensal)
        sinais = [s for s in (l.get("sinais") or []) if s.get("regra") in REGRAS_CDB]
        cresc_cap = _num(l.get("cresc_captacoes_12m"))
        base_cap = _num(l.get("captacoes_12m_atras")) or 0
        bancos.append({
            "cod": l["cod"], "nome": nomes.get(l["cod"], l["cod"]),
            "tipo": tipos.get(l.get("tcb"), "Instituição financeira"),
            "nivel": l.get("nivel_final"), "score": int(l.get("score_final") or 0),
            "liquidada": l["cod"] in liquidadas, "anomes": int(l["anomes"]),
            "custo": custo,
            "custo_cdi": round(custo / cdi_b, 4) if custo is not None and cdi_b else None,
            "custo_pares": _num(l.get("custo_rel")),
            "dep_prazo": _num(l.get("share_dep_prazo")),
            "captacoes": _num(l.get("captacoes")),
            "cresc_captacoes": cresc_cap,
            "cresc_carteira": _num(l.get("cresc_carteira_12m")),
            "acelerada": bool(cresc_cap is not None and cresc_cap > 0.5 and base_cap >= 5e8),
            "liquidez": _num(l.get("liquidez_imediata")),
            "basileia": _num(l.get("basileia")),
            "sinais": [s["texto"] for s in sinais],
        })
    return {"anomes_ref": ref, "cdi_12m": cdi_ref, "fgc_por_conglomerado": FGC_POR_CONGLOMERADO,
            "fgc_teto_4_anos": FGC_TETO_4_ANOS, "bancos": bancos}
