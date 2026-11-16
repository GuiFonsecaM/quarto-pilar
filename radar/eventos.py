"""Transforma manchetes em eventos estruturados (IA com regras fixas de reserva)."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import config as C
from . import llm

log = logging.getLogger("radar.eventos")

ARQ = C.DADOS / "eventos.parquet"

TIPOS = {
    "liquidacao_intervencao": ("Liquidação, intervenção ou RAET", 10),
    "investigacao_fraude": ("Investigação, operação policial ou suspeita de fraude", 8),
    "problema_liquidez": ("Problema de liquidez, saques ou corrida", 8),
    "atraso_pagamento": ("Atraso em pagamentos, resgates ou CDBs", 8),
    "venda_ativos_carteiras": ("Venda de carteiras ou ativos para gerar caixa", 5),
    "venda_controle_aporte": ("Venda do banco, busca de comprador ou aporte de capital", 5),
    "multa_sancao": ("Multa, processo ou sanção de regulador", 4),
    "rebaixamento_rating": ("Rebaixamento de rating", 5),
    "troca_gestao_auditor": ("Saída de executivos ou troca de auditor", 3),
    "resultado_negativo": ("Prejuízo ou resultado ruim", 3),
    "noticia_positiva": ("Notícia positiva (lucro, captação, rating melhor)", 0),
    "outro": ("Outro assunto", 0),
}

SISTEMA = """Você é analista de risco bancário. Classifique manchetes de notícias brasileiras sobre bancos.
Para cada manchete devolva: o código do banco da lista (ou null se não for nenhum dela), o tipo de evento,
a gravidade (0 = irrelevante para a saúde financeira, 1 = leve, 2 = relevante, 3 = grave),
o status (confirmado, rumor ou opiniao) e um resumo neutro de até 20 palavras.
Use só o que está na manchete. Não invente fatos. Responda apenas JSON no formato:
{"itens":[{"id":"...","cod":"C0000000 ou null","tipo":"<tipo>","gravidade":0,"status":"confirmado","resumo":"..."}]}
Tipos válidos: """ + ", ".join(TIPOS)

REGRAS = [
    ("liquidacao_intervencao", 3, r"liquida[cç][aã]o extrajudicial|interven[cç][aã]o|\braet\b|decreta liquida"),
    ("investigacao_fraude", 3, r"pol[ií]cia federal|opera[cç][aã]o .{0,30}(pf|policia)|fraude|pris[aã]o|preso|investiga"),
    ("problema_liquidez", 2, r"liquidez|corrida banc|saques em massa|socorro"),
    ("atraso_pagamento", 3, r"atras[oa].{0,30}(pagamento|resgate|cdb)|n[aã]o paga|calote|suspende resgate"),
    ("venda_ativos_carteiras", 2, r"vend[ea].{0,20}carteira|cess[aã]o de cr[eé]dito|venda de ativos"),
    ("venda_controle_aporte", 2, r"compra d[oa] banco|aquisi[cç][aã]o d[oa] banco|aporte|capitaliza|vende controle|comprador"),
    ("multa_sancao", 2, r"multa|processo administrativo|sancion|cvm (abre|instaura)"),
    ("rebaixamento_rating", 2, r"rebaix|downgrade|perspectiva negativa"),
    ("troca_gestao_auditor", 1, r"renuncia|deixa o cargo|afastad|troca de auditor|novo (ceo|presidente)"),
    ("resultado_negativo", 1, r"preju[ií]zo|lucro (cai|recua|despenca)"),
]


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def classificar_regras(titulo: str) -> tuple[str, int]:
    t = _sem_acento(titulo)
    for tipo, grav, padrao in REGRAS:
        if re.search(_sem_acento(padrao), t):
            return tipo, grav
    return "outro", 0


def _casar_banco(titulo: str, bancos: pd.DataFrame) -> str | None:
    t = _sem_acento(titulo)
    for r in bancos.itertuples():
        nomes = [r.nome_exibicao] + re.findall(r'"([^"]+)"', getattr(r, "busca", "") or "")
        for n in nomes:
            n = _sem_acento(n)
            if len(n) >= 4 and re.search(r"\b" + re.escape(n) + r"\b", t):
                return r.cod
    return None


def carregar() -> pd.DataFrame:
    if ARQ.exists():
        return pd.read_parquet(ARQ)
    return pd.DataFrame(columns=["id", "cod", "tipo", "gravidade", "status", "resumo", "metodo",
                                 "data", "titulo", "link", "fonte"])


def processar(noticias: pd.DataFrame, bancos: pd.DataFrame) -> pd.DataFrame:
    """bancos: cod, nome_exibicao. Classifica as notícias ainda não processadas."""
    ev = carregar()
    pend = noticias[~noticias["processado"].astype(bool)].copy()
    if pend.empty:
        return ev
    lista = "\n".join(f"{r.cod}: {r.nome_exibicao}" for r in bancos.itertuples())
    validos = set(bancos["cod"])
    novos, chamadas = [], 0
    blocos = [pend.iloc[i:i + C.MANCHETES_POR_CHAMADA] for i in range(0, len(pend), C.MANCHETES_POR_CHAMADA)]
    for bloco in blocos:
        resp = None
        if llm.disponivel() and chamadas < C.MAX_CHAMADAS_EXTRACAO:
            entrada = [{"id": r.id, "manchete": r.titulo, "fonte": r.fonte,
                        "banco_buscado": r.cod} for r in bloco.itertuples()]
            resp = llm.extrair(SISTEMA, f"Bancos:\n{lista}\n\nManchetes:\n{json.dumps(entrada, ensure_ascii=False)}")
            chamadas += 1
        por_id = {}
        if isinstance(resp, dict):
            for it in resp.get("itens", []):
                if isinstance(it, dict) and it.get("id"):
                    por_id[str(it["id"])] = it
        for r in bloco.itertuples():
            it = por_id.get(r.id)
            if it and it.get("tipo") in TIPOS:
                cod = it.get("cod") if it.get("cod") in validos else None
                cod = cod or (r.cod if r.cod in validos else None)
                try:
                    grav = max(0, min(3, int(it.get("gravidade", 0))))
                except (TypeError, ValueError):
                    grav = 0
                novos.append({"id": r.id, "cod": cod, "tipo": it["tipo"], "gravidade": grav,
                              "status": str(it.get("status", ""))[:12], "resumo": str(it.get("resumo", ""))[:200],
                              "metodo": "ia"})
            else:
                tipo, grav = classificar_regras(r.titulo)
                cod = r.cod if r.cod in validos else _casar_banco(r.titulo, bancos)
                novos.append({"id": r.id, "cod": cod, "tipo": tipo, "gravidade": grav, "status": "",
                              "resumo": "", "metodo": "regras"})
    n = pd.DataFrame(novos).merge(noticias[["id", "data", "titulo", "link", "fonte"]], on="id", how="left")
    ev = pd.concat([ev, n], ignore_index=True).drop_duplicates("id", keep="last")
    ev.to_parquet(ARQ, index=False)
    noticias.loc[noticias["id"].isin(n["id"]), "processado"] = True
    noticias.to_parquet(C.DADOS / "noticias.parquet", index=False)
    log.info("Eventos classificados: %s (chamadas de IA: %s)", len(n), chamadas)
    return ev


def score_noticias(ev: pd.DataFrame, hoje: datetime | None = None) -> pd.DataFrame:
    """Pontos de notícias por banco (0–30), com peso que cai ao longo de 45 dias."""
    hoje = hoje or datetime.now(timezone.utc)
    if ev.empty:
        return pd.DataFrame(columns=["cod", "score_noticias", "eventos_graves"])
    e = ev[ev["cod"].notna()].copy()
    e["dt"] = pd.to_datetime(e["data"], utc=True, errors="coerce")
    e = e[e["dt"] >= hoje - timedelta(days=C.JANELA_NOTICIAS_DIAS)]
    if e.empty:
        return pd.DataFrame(columns=["cod", "score_noticias", "eventos_graves"])
    idade = (hoje - e["dt"]).dt.days.clip(lower=0)
    peso = 1 - 0.7 * idade / C.JANELA_NOTICIAS_DIAS
    base = e["tipo"].map(lambda t: TIPOS.get(t, ("", 0))[1])
    fator = e["gravidade"].astype(float) / 3
    rumor = e["status"].astype(str).str.startswith("rumor").map({True: 0.5, False: 1.0})
    e["pts"] = base * fator * peso * rumor
    # o mesmo tipo de evento conta no máximo 2 vezes (evita inflar com várias matérias iguais)
    e = e.sort_values("pts", ascending=False).groupby(["cod", "tipo"]).head(2)
    g = e.groupby("cod").agg(score_noticias=("pts", "sum"),
                             eventos_graves=("gravidade", lambda x: int((x >= 2).sum())))
    g["score_noticias"] = g["score_noticias"].clip(upper=30).round().astype(int)
    return g.reset_index()
