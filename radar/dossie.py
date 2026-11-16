"""Dossiê por banco em alerta: a IA cruza números e notícias, sempre citando a evidência.

Regra anti-alucinação: a IA só pode se apoiar em fatos numerados (F1, F2...) e notícias
numeradas (N1, N2...) que nós mesmos fornecemos. Pontos sem evidência válida são descartados,
e os valores mostrados no site vêm dos nossos dados, nunca do texto da IA.
"""
from __future__ import annotations

import hashlib
import json
import logging

import pandas as pd

from . import config as C
from . import llm
from .eventos import TIPOS

log = logging.getLogger("radar.dossie")

ARQ = C.DADOS / "dossies.json"

SISTEMA = """Você é analista de risco bancário e escreve em português do Brasil, em linguagem simples.
Receberá FATOS numéricos (F1, F2...) de dados públicos do Banco Central e NOTÍCIAS (N1, N2...) sobre um banco.
Tarefa: explicar por que o banco aparece no radar e apontar onde números e notícias NÃO CONDIZEM entre si.
Regras obrigatórias:
- Cada ponto precisa citar ao menos uma evidência pelos códigos fornecidos (ex.: ["F2","N1"]).
- Não invente números, fatos ou fontes. Não repita valores que não estejam nos fatos.
- Tom neutro: são sinais estatísticos, não acusações nem recomendação de investimento.
Responda só JSON: {"resumo":"2 a 3 frases","pontos":[{"texto":"...","evidencias":["F1"]}],
"contradicoes":[{"texto":"...","evidencias":["F3","N2"]}],"acompanhar":["o que observar no próximo trimestre"]}"""


def _carregar() -> dict:
    if ARQ.exists():
        return json.loads(ARQ.read_text(encoding="utf-8"))
    return {}


def _fatos(linha: pd.Series) -> list[dict]:
    fatos = [{"id": f"F{k + 1}", "texto": s["texto"]} for k, s in enumerate(linha["sinais"][:8])]

    def pct(v):
        return None if pd.isna(v) else f"{v * 100:.1f}%".replace(".", ",")

    extras = [
        ("Índice de Basileia", pct(linha.get("basileia"))),
        ("Crescimento da captação em 12 meses", pct(linha.get("cresc_captacoes_12m"))),
        ("Crescimento da carteira de crédito em 12 meses", pct(linha.get("cresc_carteira_12m"))),
        ("Custo de captação em 12 meses", pct(linha.get("custo_captacao"))),
        ("Liquidez imediata sobre a captação", pct(linha.get("liquidez_imediata"))),
        ("ROE em 12 meses", pct(linha.get("roe"))),
    ]
    for nome, v in extras:
        if v is not None:
            a = int(linha["anomes"])
            mes = {3: "mar", 6: "jun", 9: "set", 12: "dez"}[a % 100]
            fatos.append({"id": f"F{len(fatos) + 1}", "texto": f"{nome}: {v} (balanço de {mes}/{a // 100})"})
    return fatos


def _noticias(ev: pd.DataFrame, cod: str) -> list[dict]:
    if ev.empty:
        return []
    e = ev[(ev["cod"] == cod) & (ev["gravidade"] >= 1)].sort_values("data", ascending=False).head(8)
    return [{"id": f"N{k + 1}", "texto": r.titulo, "data": str(r.data)[:10], "fonte": r.fonte, "link": r.link,
             "tipo": TIPOS.get(r.tipo, ("Outro", 0))[0]} for k, r in enumerate(e.itertuples())]


def _validar(saida: dict, ids: set) -> dict:
    def limpar(lista):
        out = []
        for p in lista or []:
            if not isinstance(p, dict):
                continue
            ev = [e for e in p.get("evidencias", []) if e in ids]
            if ev and p.get("texto"):
                out.append({"texto": str(p["texto"])[:400], "evidencias": ev})
        return out
    return {"resumo": str(saida.get("resumo", ""))[:600],
            "pontos": limpar(saida.get("pontos"))[:6],
            "contradicoes": limpar(saida.get("contradicoes"))[:4],
            "acompanhar": [str(a)[:200] for a in (saida.get("acompanhar") or [])][:4]}


def _por_regras(nome: str, fatos: list[dict], noticias: list[dict]) -> dict:
    pontos = [{"texto": f["texto"], "evidencias": [f["id"]]} for f in fatos[:4]]
    resumo = f"{nome} aparece no radar por {len(pontos)} sinal(is) nos dados públicos do Banco Central"
    resumo += f" e {len(noticias)} notícia(s) relevante(s) recente(s)." if noticias else "."
    return {"resumo": resumo, "pontos": pontos, "contradicoes": [], "acompanhar": []}


def gerar(atual: pd.DataFrame, ev: pd.DataFrame, nomes: dict) -> dict:
    """atual: scores do último trimestre com score_final. Devolve {cod: dossiê}."""
    cache = _carregar()
    alvo = atual[atual["score_final"] >= 45].sort_values("score_final", ascending=False)
    novos, feitos = {}, 0
    for _, l in alvo.iterrows():
        cod = l["cod"]
        nome = nomes.get(cod, cod)
        fatos, notis = _fatos(l), _noticias(ev, cod)
        chave = hashlib.sha1(json.dumps([fatos, [n["texto"] for n in notis]], ensure_ascii=False)
                             .encode()).hexdigest()[:12]
        if cod in cache and cache[cod].get("chave") == chave:
            novos[cod] = cache[cod]
            continue
        corpo = None
        if llm.disponivel() and feitos < C.MAX_DOSSIES:
            entrada = (f"Banco: {nome}\nScore: {int(l['score_final'])}/100\n\nFATOS:\n" +
                       "\n".join(f"{f['id']}: {f['texto']}" for f in fatos) + "\n\nNOTÍCIAS:\n" +
                       ("\n".join(f"{n['id']} ({n['data']}, {n['fonte']}): {n['texto']}" for n in notis) or "nenhuma"))
            saida = llm.redigir(SISTEMA, entrada)
            feitos += 1
            if isinstance(saida, dict):
                corpo = _validar(saida, {f["id"] for f in fatos} | {n["id"] for n in notis})
                corpo["metodo"] = "ia"
                if not corpo["pontos"]:
                    corpo = None
        if corpo is None:
            corpo = _por_regras(nome, fatos, notis)
            corpo["metodo"] = "regras"
        corpo.update({"chave": chave, "fatos": fatos, "noticias": notis, "anomes": int(l["anomes"])})
        novos[cod] = corpo
    ARQ.write_text(json.dumps(novos, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Dossiês: %s (novos com IA: %s)", len(novos), feitos)
    return novos
