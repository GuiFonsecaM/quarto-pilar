"""Coleta diária de notícias (Google News RSS e GDELT) por banco monitorado."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser
import pandas as pd

from . import config as C
from .http import get, sessao

log = logging.getLogger("radar.noticias")

ARQ = C.DADOS / "noticias.parquet"
COLS = ["id", "data", "titulo", "fonte", "link", "cod", "consulta", "origem", "coletado_em", "processado"]

# Buscas gerais do setor (a IA tenta ligar cada manchete a um banco)
BUSCAS_SETOR = [
    '"liquidação extrajudicial" banco',
    '"Banco Central" intervenção banco',
    'FGC banco ressarcimento',
    'banco "dificuldade de liquidez"',
    'banco CDB atraso resgate',
    '"Polícia Federal" banco fraude carteira',
]

_SIGLAS = r"\b(S\.?A\.?|S/A|SCFI|CFI|BM|LTDA\.?|IP|CCVM|DTVM|SCD|BCO)\b"


def nome_exibicao(nome: str) -> str:
    n = re.sub(r"\s*-\s*PRUDENCIAL.*$", "", str(nome), flags=re.I).strip()
    if " - " in n:
        n = n.split(" - ")[-1]
    n = re.sub(_SIGLAS, "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" .-")
    pequenas = {"de", "do", "da", "dos", "das", "e"}
    return " ".join(w.lower() if w.lower() in pequenas else (w if w.isupper() and len(w) <= 3 else w.capitalize())
                    for w in n.split())


def apelidos() -> pd.DataFrame:
    arq = C.CONFIG / "apelidos.csv"
    if not arq.exists():
        return pd.DataFrame(columns=["cod", "nome_exibicao", "busca"])
    return pd.read_csv(arq, dtype=str).drop_duplicates("cod")


def termos(bancos: pd.DataFrame) -> pd.DataFrame:
    """bancos: colunas cod, nome. Devolve cod, nome_exibicao, busca."""
    ap = apelidos().set_index("cod")
    out = []
    for r in bancos.itertuples():
        if r.cod in ap.index:
            out.append((r.cod, ap.loc[r.cod, "nome_exibicao"], ap.loc[r.cod, "busca"]))
        else:
            ex = nome_exibicao(r.nome)
            out.append((r.cod, ex, f'"{ex}"'))
    return pd.DataFrame(out, columns=["cod", "nome_exibicao", "busca"])


def _id(link: str, titulo: str) -> str:
    base = re.sub(r"\W+", "", (titulo or "").lower())[:120] or link
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def google_news(s, consulta: str, dias: int = 2) -> list[dict]:
    q = quote(f"{consulta} when:{dias}d")
    url = f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    r = get(s, url, headers={"Accept": "application/rss+xml"}, tentativas=2, timeout=30)
    if r is None:
        return []
    feed = feedparser.parse(r.text)
    itens = []
    for e in feed.entries[:30]:
        titulo = re.sub(r"\s+-\s+[^-]+$", "", e.get("title", "")).strip()
        fonte = (e.get("source") or {}).get("title") or ""
        try:
            data = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            data = datetime.now(timezone.utc).isoformat()
        itens.append({"titulo": titulo, "fonte": fonte, "link": e.get("link", ""), "data": data,
                      "origem": "google_news"})
    return itens


def gdelt(s, consulta: str, dias: int = 2) -> list[dict]:
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": f"{consulta} sourcelang:portuguese", "mode": "artlist", "format": "json",
              "maxrecords": 50, "timespan": f"{dias}d", "sort": "datedesc"}
    r = get(s, url, params=params, tentativas=2, timeout=30)
    if r is None:
        return []
    try:
        arts = r.json().get("articles", [])
    except ValueError:
        return []
    itens = []
    for a in arts:
        try:
            data = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            data = datetime.now(timezone.utc).isoformat()
        itens.append({"titulo": a.get("title", ""), "fonte": a.get("domain", ""), "link": a.get("url", ""),
                      "data": data, "origem": "gdelt"})
    return itens


def carregar() -> pd.DataFrame:
    if ARQ.exists():
        return pd.read_parquet(ARQ)
    return pd.DataFrame(columns=COLS)


def coletar(alvos: pd.DataFrame, dias: int = 2, usar_gdelt: bool = True) -> pd.DataFrame:
    """alvos: cod, nome_exibicao, busca. Acrescenta as notícias novas ao arquivo e devolve o total."""
    s = sessao()
    antigas = carregar()
    vistos = set(antigas["id"]) if not antigas.empty else set()
    agora = datetime.now(timezone.utc).isoformat()
    novas = []

    def guardar(itens, cod, consulta):
        for it in itens:
            if not it["titulo"]:
                continue
            i = _id(it["link"], it["titulo"])
            if i in vistos:
                continue
            vistos.add(i)
            novas.append({**it, "id": i, "cod": cod, "consulta": consulta, "coletado_em": agora,
                          "processado": False})

    for r in alvos.itertuples():
        guardar(google_news(s, r.busca, dias), r.cod, r.busca)
        time.sleep(1.0)
    for b in BUSCAS_SETOR:
        guardar(google_news(s, b, dias), None, b)
        if usar_gdelt:
            guardar(gdelt(s, b, dias), None, b)
        time.sleep(1.0)
    log.info("Notícias novas: %s", len(novas))
    df = pd.concat([antigas, pd.DataFrame(novas, columns=COLS)], ignore_index=True)
    # mantém 365 dias
    limite = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    df = df[df["data"].astype(str) >= limite]
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ARQ, index=False)
    return df
