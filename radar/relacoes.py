"""Relacionamentos entre instituições: quem vendeu carteira para quem, quem comprou quem, fundos em comum.

Duas fontes:
- config/relacoes_conhecidas.csv: casos documentados na imprensa, revisados à mão, com link;
- eventos extraídos das notícias do dia (a IA aponta a contraparte e o tipo de relação).

Cada ligação é guardada uma vez (A → B) com o texto do ponto de vista de A e de B.
"""
from __future__ import annotations

import pandas as pd

from . import config as C

# relação: (texto para A, texto para B) — {a} e {b} são os nomes
RELACOES = {
    "venda_carteira": ("Vendeu carteira de crédito para {b}", "Comprou carteira de crédito de {a}"),
    "compra_carteira": ("Comprou carteira de crédito de {b}", "Vendeu carteira de crédito para {a}"),
    "venda_controle": ("Negocia ou acertou a venda para {b}", "Negocia ou acertou a compra de {a}"),
    "tentativa_aquisicao": ("Tentou comprar {b}", "Foi alvo de tentativa de compra por {a}"),
    "aporte_recebido": ("Recebeu aporte de {b}", "Fez aporte em {a}"),
    "ativos_em_comum": ("Tem ativos ou fundos em comum com {b}", "Tem ativos ou fundos em comum com {a}"),
    "parceria": ("Tem parceria ou contrato com {b}", "Tem parceria ou contrato com {a}"),
    "citado_junto": ("Citado com {b} em notícia", "Citado com {a} em notícia"),
}
COLS = ["cod_a", "nome_a", "cod_b", "nome_b", "relacao", "desc_a", "desc_b", "data", "fonte", "link", "origem"]


def conhecidas() -> pd.DataFrame:
    arq = C.CONFIG / "relacoes_conhecidas.csv"
    if not arq.exists():
        return pd.DataFrame(columns=COLS)
    d = pd.read_csv(arq, dtype=str).fillna("")
    d["origem"] = "curadoria"
    return d.reindex(columns=COLS)


def de_eventos(ev: pd.DataFrame, nomes: dict) -> pd.DataFrame:
    """Ligações a partir dos eventos de notícias que têm contraparte."""
    if ev is None or ev.empty or "contraparte" not in ev:
        return pd.DataFrame(columns=COLS)
    e = ev[ev["cod"].notna() & ev["contraparte"].fillna("").astype(str).str.len().gt(1)].copy()
    e = e[e["relacao"].isin(RELACOES)]
    out = []
    for r in e.itertuples():
        a = nomes.get(r.cod, r.cod)
        cod_b = r.contraparte_cod if isinstance(r.contraparte_cod, str) and r.contraparte_cod else ""
        if cod_b == r.cod:
            continue
        b = nomes.get(cod_b, r.contraparte) if cod_b else r.contraparte
        ta, tb = RELACOES[r.relacao]
        out.append({"cod_a": r.cod, "nome_a": a, "cod_b": cod_b, "nome_b": b, "relacao": r.relacao,
                    "desc_a": ta.format(a=a, b=b), "desc_b": tb.format(a=a, b=b),
                    "data": str(r.data)[:10], "fonte": r.fonte, "link": r.link, "origem": "notícia"})
    return pd.DataFrame(out, columns=COLS)


def montar(ev: pd.DataFrame, nomes: dict) -> pd.DataFrame:
    d = pd.concat([conhecidas(), de_eventos(ev, nomes)], ignore_index=True)
    if d.empty:
        return d
    # mesma dupla e mesmo tipo de relação: fica a mais recente (curadoria tem prioridade)
    d["prio"] = (d["origem"] == "curadoria").astype(int)
    d["par"] = d.apply(lambda r: "|".join(sorted([r.cod_a, r.cod_b or r.nome_b.lower()])) + "|" + r.relacao, axis=1)
    d = d.sort_values(["prio", "data"], ascending=False).drop_duplicates("par").drop(columns=["prio", "par"])
    return d.sort_values("data", ascending=False).reset_index(drop=True)


def do_banco(rel: pd.DataFrame, cod: str, no_site: set) -> list[dict]:
    """Ligações de um banco, escritas do ponto de vista dele."""
    if rel is None or rel.empty:
        return []
    out = []
    for r in rel[(rel["cod_a"] == cod) | (rel["cod_b"] == cod)].itertuples():
        lado_a = r.cod_a == cod
        outro_cod = r.cod_b if lado_a else r.cod_a
        out.append({
            "outro": r.nome_b if lado_a else r.nome_a,
            "outro_cod": outro_cod if outro_cod in no_site else None,
            "descricao": r.desc_a if lado_a else r.desc_b,
            "data": r.data, "fonte": r.fonte, "link": r.link, "origem": r.origem,
        })
    return out[:20]
