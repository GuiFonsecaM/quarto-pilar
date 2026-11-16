"""Gera os arquivos JSON que o site estático (pasta docs/) lê."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import config as C
from .eventos import TIPOS

TIPO_INST = {"B1": "Banco comercial ou múltiplo", "B2": "Banco de investimento", "B3S": "Cooperativa de crédito",
             "B4": "Banco de desenvolvimento", "N1": "Financeira ou instituição de crédito"}

SERIES = {
    "basileia": "basileia", "indice_cp": "indice_capital_principal", "cresc_captacoes": "cresc_captacoes_12m",
    "cresc_carteira": "cresc_carteira_12m", "custo": "custo_captacao", "liquidez": "liquidez_imediata",
    "ativos_outros": "share_ativos_outros", "roe": "roe", "ativo_total": "ativo_total", "captacoes": "captacoes",
    "score": "score_dados",
}
PARES = {"basileia_pares": "basileia", "custo_pares": "custo_captacao", "liquidez_pares": "liquidez_imediata",
         "cresc_captacoes_pares": "cresc_captacoes_12m"}


def _limpo(v):
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    if hasattr(v, "item"):
        return _limpo(v.item())
    return v


def _escrever(caminho, obj) -> bool:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_limpo)
    if caminho.exists() and caminho.read_text(encoding="utf-8") == txt:
        return False
    caminho.write_text(txt, encoding="utf-8")
    return True


def _lista(serie: pd.Series):
    return [_limpo(x) for x in serie.tolist()]


def construir(scores: pd.DataFrame, atual: pd.DataFrame, ev: pd.DataFrame, dossies: dict,
              backtest: dict | None, nomes: dict, historico: pd.DataFrame | None = None,
              liquidadas: set | None = None) -> dict:
    liquidadas = liquidadas or set()
    agora = datetime.now(timezone.utc)
    ref = int(atual["anomes"].max())
    medianas = scores.groupby(["anomes", "grupo"])[list(set(PARES.values()))].median()

    ev = ev.copy() if ev is not None else pd.DataFrame()
    if not ev.empty:
        ev["dt"] = pd.to_datetime(ev["data"], utc=True, errors="coerce")
    ranking = []
    anterior = scores[scores["anomes"] < ref].sort_values("anomes").groupby("cod").tail(1).set_index("cod")
    for _, l in atual.sort_values("score_final", ascending=False).iterrows():
        cod = l["cod"]
        h = scores[scores["cod"] == cod].sort_values("anomes").tail(32)
        serie = {"anomes": [int(x) for x in h["anomes"]]}
        for k, col in SERIES.items():
            serie[k] = _lista(h[col])
        for k, col in PARES.items():
            serie[k] = [_limpo(medianas.loc[(a, g), col]) if (a, g) in medianas.index else None
                        for a, g in zip(h["anomes"], h["grupo"])]
        notis = []
        n30 = graves = 0
        if not ev.empty:
            e = ev[(ev["cod"] == cod) & (ev["dt"] >= agora - timedelta(days=120))].sort_values("dt", ascending=False)
            n30 = int((e["dt"] >= agora - timedelta(days=30)).sum())
            graves = int(((e["gravidade"] >= 2) & (e["dt"] >= agora - timedelta(days=C.JANELA_NOTICIAS_DIAS))).sum())
            for r in e.head(40).itertuples():
                notis.append({"data": str(r.data)[:10], "titulo": r.titulo, "fonte": r.fonte, "link": r.link,
                              "tipo": r.tipo, "tipo_label": TIPOS.get(r.tipo, ("Outro", 0))[0],
                              "gravidade": int(r.gravidade), "status": r.status, "resumo": r.resumo,
                              "metodo": r.metodo})
        hist = []
        if historico is not None and not historico.empty:
            hh = historico[historico["cod"] == cod].tail(120)
            hist = [[d, int(s)] for d, s in zip(hh["data"], hh["score_final"])]
        prev = anterior["score_dados"].get(cod) if cod in anterior.index else None
        info = {
            "cod": cod, "nome": nomes.get(cod, cod), "nome_oficial": l.get("nome"),
            "tipo": TIPO_INST.get(l.get("tcb"), "Instituição financeira"), "segmento": l.get("segmento"),
            "grupo_pares": l.get("grupo"), "anomes_ref": int(l["anomes"]), "defasado": int(l["anomes"]) < ref,
            "score_final": int(l["score_final"]), "score_dados": int(l["score_dados"]),
            "score_noticias": int(l["score_noticias"]), "nivel": l["nivel_final"], "sinais": l["sinais"],
            "liquidada": cod in liquidadas,
            "serie": serie, "historico_diario": hist, "noticias": notis, "dossie": dossies.get(cod),
        }
        _escrever(C.SITE_DADOS / "bancos" / f"{cod}.json", info)
        ranking.append({
            "cod": cod, "nome": info["nome"], "tipo": info["tipo"], "segmento": l.get("segmento"),
            "ativo": _limpo(l["ativo_total"]), "basileia": _limpo(l["basileia"]),
            "score": info["score_final"], "score_dados": info["score_dados"],
            "score_noticias": info["score_noticias"], "nivel": info["nivel"],
            "variacao": None if prev is None or pd.isna(prev) else int(l["score_dados"] - prev),
            "sinais": [s["texto"] for s in l["sinais"][:2]], "noticias_30d": n30, "eventos_graves": graves,
            "spark": [int(x) for x in h["score_dados"].tail(12)],
            "anomes_ref": int(l["anomes"]), "defasado": int(l["anomes"]) < ref, "liquidada": cod in liquidadas,
        })
    ativos = [r for r in ranking if not r["liquidada"]]
    contagem = pd.Series([r["nivel"] for r in ativos]).value_counts().to_dict()
    meta = {"atualizado_em": agora.isoformat(timespec="minutes"), "anomes_ref": ref, "total": len(ativos),
            "niveis": contagem, "minimo_basileia": C.BASILEIA_MINIMO, "ativo_minimo": C.ATIVO_MINIMO}
    _escrever(C.SITE_DADOS / "ranking.json", ranking)
    _escrever(C.SITE_DADOS / "meta.json", meta)
    if backtest:
        _escrever(C.SITE_DADOS / "backtest.json", backtest)
    # remove páginas de bancos que saíram do universo
    vivos = {r["cod"] for r in ranking}
    for arq in (C.SITE_DADOS / "bancos").glob("*.json"):
        if arq.stem not in vivos:
            arq.unlink()
    return meta
