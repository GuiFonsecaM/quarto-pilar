"""Linha de comando do Quarto Pilar.

    python -m radar carga-inicial   baixa todo o histórico do IF.Data (2014 em diante)
    python -m radar trimestral      atualiza dados do BC, score e backtest
    python -m radar diario          rotina do dia: BC (se houver data-base nova), notícias, IA e site
    python -m radar site            só regenera o site com o que já existe
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone

import pandas as pd

from . import backtest, config as C, dossie, eventos, ifdata, indicadores, llm, noticias, painel, score, site

log = logging.getLogger("radar")
ARQ_SCORES = C.DADOS / "scores.parquet"
ARQ_BACKTEST = C.DADOS / "backtest.json"
ARQ_HIST = C.DADOS / "historico_diario.parquet"


def salvar_scores(s: pd.DataFrame) -> None:
    s = s.copy()
    s["sinais"] = s["sinais"].map(lambda x: json.dumps(x, ensure_ascii=False, default=float))
    C.DADOS.mkdir(parents=True, exist_ok=True)
    s.to_parquet(ARQ_SCORES, index=False)


def carregar_scores() -> pd.DataFrame:
    s = pd.read_parquet(ARQ_SCORES)
    s["sinais"] = s["sinais"].map(json.loads)
    return s


def trimestral(completo: bool = False, refazer_ultimos: int = 2, forcar: bool = False) -> bool:
    novos = ifdata.atualizar(completo=completo, refazer_ultimos=refazer_ultimos)
    if not (novos or forcar or not ARQ_SCORES.exists()):
        log.info("Nenhuma data-base nova no IF.Data.")
        return False
    v, c = ifdata.carregar_brutos()
    if v.empty:
        log.error("Sem dados brutos do IF.Data. Verifique a conexão com o Banco Central.")
        return False
    p = painel.montar(v, c)
    p.to_parquet(C.BRUTOS / "painel.parquet", index=False)
    s = score.calcular(indicadores.calcular(p))
    salvar_scores(s)
    res = backtest.rodar(s, c)
    ARQ_BACKTEST.write_text(json.dumps(res, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    (C.RAIZ / "relatorios").mkdir(exist_ok=True)
    (C.RAIZ / "relatorios" / "backtest.md").write_text(backtest.markdown(res), encoding="utf-8")
    log.info("Scores: %s linhas; backtest: %s/%s quebras com alerta prévio", len(s), res["detectados"], res["total"])
    return True


def ultimo_trimestre(s: pd.DataFrame) -> pd.DataFrame:
    cont = s.groupby("anomes").size()
    ref = cont[cont >= 0.8 * cont.tail(8).median()].index.max()
    atual = s[s["anomes"] == ref].copy()
    # bancos que não divulgaram a última data-base continuam visíveis com o último dado
    faltam = s[(s["anomes"] < ref) & (s["anomes"] >= ref - 100) & ~s["cod"].isin(atual["cod"])]
    faltam = faltam.sort_values("anomes").groupby("cod").tail(1)
    return pd.concat([atual, faltam], ignore_index=True)


def nomes_exibicao(atual: pd.DataFrame) -> dict:
    t = noticias.termos(atual[["cod", "nome"]])
    return dict(zip(t["cod"], t["nome_exibicao"]))


def montar_site(atual: pd.DataFrame, s: pd.DataFrame, ev: pd.DataFrame, buscar_ia: bool = True) -> dict:
    sn = eventos.score_noticias(ev)
    atual = atual.drop(columns=["score_noticias", "eventos_graves"], errors="ignore").merge(sn, on="cod", how="left")
    atual["score_noticias"] = atual["score_noticias"].fillna(0).astype(int)
    atual["score_final"] = (atual["score_dados"] + atual["score_noticias"]).clip(upper=100).astype(int)
    atual["nivel_final"] = atual["score_final"].map(score.nivel)
    nomes = nomes_exibicao(atual)
    dossies = dossie.gerar(atual, ev, nomes)
    hoje = date.today().isoformat()
    h = pd.read_parquet(ARQ_HIST) if ARQ_HIST.exists() else pd.DataFrame(columns=["data", "cod", "score_final"])
    h = pd.concat([h[h["data"] != hoje], atual.assign(data=hoje)[["data", "cod", "score_final"]]], ignore_index=True)
    h.to_parquet(ARQ_HIST, index=False)
    bt = json.loads(ARQ_BACKTEST.read_text(encoding="utf-8")) if ARQ_BACKTEST.exists() else None
    liquidadas = {c["cod"] for c in (bt or {}).get("casos", [])}
    meta = site.construir(s, atual, ev, dossies, bt, nomes, h, liquidadas)
    meta["uso_ia"] = llm.uso()
    return meta


def diario() -> None:
    segunda = datetime.now(timezone.utc).weekday() == 0
    trimestral(refazer_ultimos=2 if segunda else 0)
    if not ARQ_SCORES.exists():
        log.error("Ainda não há scores. Rode a carga inicial.")
        return
    s = carregar_scores()
    atual = ultimo_trimestre(s)
    t = noticias.termos(atual[["cod", "nome"]])
    prioridade = atual.assign(o=atual["score_dados"] * 1e15 + atual["ativo_total"]).sort_values("o", ascending=False)
    em_alerta = prioridade[prioridade["score_dados"] >= 25]["cod"]
    maiores = atual.sort_values("ativo_total", ascending=False)["cod"]
    alvo_cods = list(dict.fromkeys(list(em_alerta) + list(maiores)))[:C.BANCOS_NOTICIAS]
    alvos = t[t["cod"].isin(alvo_cods)]
    n = noticias.coletar(alvos)
    ev = eventos.processar(n, alvos[["cod", "nome_exibicao", "busca"]])
    meta = montar_site(atual, s, ev)
    log.info("Site atualizado: %s", meta)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="radar")
    ap.add_argument("comando", choices=["carga-inicial", "trimestral", "diario", "site"])
    a = ap.parse_args()
    if a.comando == "carga-inicial":
        trimestral(completo=True, forcar=True)
        s = carregar_scores()
        montar_site(ultimo_trimestre(s), s, eventos.carregar(), buscar_ia=False)
    elif a.comando == "trimestral":
        trimestral(forcar=True)
    elif a.comando == "diario":
        diario()
    elif a.comando == "site":
        s = carregar_scores()
        montar_site(ultimo_trimestre(s), s, eventos.carregar(), buscar_ia=False)


if __name__ == "__main__":
    main()
