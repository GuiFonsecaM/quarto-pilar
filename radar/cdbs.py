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


def _p(v, casas=1):
    return f"{v * 100:.{casas}f}%".replace(".", ",")


def _x(v):
    return f"{v:.1f}x".replace(".", ",")


def _tri(anomes: int) -> str:
    a, m = divmod(int(anomes), 100)
    return f"{ {3: 'mar', 6: 'jun', 9: 'set', 12: 'dez'}.get(m, m)}/{str(a)[2:]}"


def analisar(l, antes, cdi_b: float | None, regras: set) -> dict:
    """Dossiê do ponto de vista de quem compra CDB do banco. Só usa números do balanço;
    cada item tem um tom: bom, neutro, atencao ou ruim."""
    itens = []

    def item(titulo, tom, texto):
        itens.append({"titulo": titulo, "tom": tom, "texto": texto})

    g = lambda k, src=l: _num(src.get(k)) if src is not None else None
    custo, rel, rel_antes = g("custo_captacao"), g("custo_rel"), g("custo_rel", antes)

    # 1. Quanto paga para captar
    if custo is not None:
        t = f"Pagou em média {_p(custo)} ao ano sobre tudo o que captou"
        if cdi_b:
            t += f", o equivalente a {round(custo / cdi_b * 100)}% do CDI do período"
        if rel is not None:
            t += f", {_x(rel)} a mediana de bancos parecidos"
        t += "."
        if rel is not None and rel_antes is not None and abs(rel - rel_antes) >= 0.15:
            t += f" Há um ano era {_x(rel_antes)}: o custo relativo {'subiu' if rel > rel_antes else 'caiu'}."
        tom = "neutro" if rel is None else "ruim" if rel >= 1.5 else "atencao" if rel >= 1.25 else "bom" if rel < 0.9 else "neutro"
        dep0 = g("share_dep_prazo")
        if tom in ("ruim", "atencao") and dep0 is not None and dep0 < 0.2:
            tom = "atencao"
            t += " Como o banco quase não capta com CDB, esse custo vem de outras fontes (letras, repasses, poupança) e diz pouco sobre a taxa de um CDB dele."
        elif tom in ("ruim", "atencao"):
            t += " Pagar bem acima dos concorrentes costuma indicar que o banco precisa de dinheiro e tem dificuldade de conseguir mais barato."
        item("Custo para captar", tom, t)

    # 2. Dependência de CDB
    dep = g("share_dep_prazo")
    if dep is not None:
        if dep > 0.9:
            item("Dependência de CDB", "ruim", f"{_p(dep, 0)} da captação vem de depósitos a prazo (CDB). O banco depende quase só de investidores que podem não renovar no vencimento.")
        elif dep > 0.7:
            item("Dependência de CDB", "atencao", f"{_p(dep, 0)} da captação vem de CDB. Fontes de dinheiro pouco diversificadas deixam o banco mais sensível a uma corrida de investidores.")
        elif dep < 0.01:
            item("Dependência de CDB", "neutro", "O banco praticamente não capta com CDB; o dinheiro vem de outras fontes.")
        elif dep < 0.4:
            item("Dependência de CDB", "bom", f"Só {_p(dep, 0)} da captação vem de CDB; o restante vem de outras fontes, como conta corrente, poupança e letras.")
        else:
            item("Dependência de CDB", "neutro", f"{_p(dep, 0)} da captação vem de CDB, com outras fontes de dinheiro complementando.")

    # 3. Captação x carteira
    cc, cr = g("cresc_captacoes_12m"), g("cresc_carteira_12m")
    if cc is not None:
        t = f"Em 12 meses a captação {'cresceu' if cc >= 0 else 'caiu'} {_p(abs(cc), 0)}"
        t += f" e a carteira de crédito {'cresceu' if (cr or 0) >= 0 else 'caiu'} {_p(abs(cr), 0)}." if cr is not None else "."
        if "captacao_acelerada" in regras:
            item("Ritmo de captação", "ruim", t + " Captar muito rápido, pagando caro, foi um dos padrões do Banco Master antes da liquidação.")
        elif "captacao_sem_credito" in regras or (cr is not None and cc - cr > 0.3):
            item("Ritmo de captação", "atencao", t + " O banco está captando bem mais rápido do que empresta; vale entender onde o dinheiro está sendo aplicado.")
        elif cc < -0.15:
            item("Ritmo de captação", "atencao", t + " Uma queda forte na captação pode indicar saída de investidores ou encolhimento do banco.")
        else:
            item("Ritmo de captação", "neutro", t + " Captação e crédito andam em ritmo compatível.")

    # 4. Caixa
    liq = g("liquidez_imediata")
    if liq is not None:
        lt = _p(min(liq, 9.99))
        if "liquidez_baixa" in regras:
            item("Dinheiro em caixa", "ruim", f"Caixa e aplicações de liquidez imediata equivalem a {lt} da captação, bem abaixo dos pares. Pouca folga para pagar resgates.")
        elif liq >= 0.2:
            item("Dinheiro em caixa", "bom", f"Caixa e aplicações de liquidez imediata equivalem a {lt} da captação, uma folga confortável para resgates.")
        else:
            item("Dinheiro em caixa", "neutro", f"Caixa e aplicações de liquidez imediata equivalem a {lt} da captação.")

    # 5. Capital
    b = g("basileia")
    if b is None:
        if "capital_nao_divulgado" in regras:
            item("Capital (colchão para perdas)", "atencao", "O banco deixou de divulgar o Índice de Basileia neste trimestre, depois de divulgar antes.")
    else:
        folga = b - C.BASILEIA_MINIMO
        t = f"Índice de Basileia de {_p(b)}, contra o mínimo de {_p(C.BASILEIA_MINIMO)}."
        if folga < 0:
            item("Capital (colchão para perdas)", "ruim", t + " O banco está abaixo do mínimo exigido: o capital próprio não cobre os riscos que ele assume.")
        elif folga < 0.025:
            item("Capital (colchão para perdas)", "atencao", t + " Pouca margem: um prejuízo moderado já levaria o banco ao limite.")
        elif folga >= 0.05:
            item("Capital (colchão para perdas)", "bom", t + " Margem confortável acima do mínimo.")
        else:
            item("Capital (colchão para perdas)", "neutro", t)

    # 6. Inadimplência
    inad, irel = g("inadimplencia"), g("inad_rel")
    if inad is not None:
        t = f"{_p(inad)} da carteira de pessoas e empresas está vencida há mais de 15 dias"
        t += f" ({_x(irel)} a mediana dos pares)." if irel is not None else "."
        if "inadimplencia_alta" in regras:
            item("Calote dos clientes", "ruim", t + " Calote alto corrói o lucro e, depois, o capital.")
        elif "inadimplencia_subindo" in regras:
            item("Calote dos clientes", "atencao", t + " A inadimplência subiu forte no último ano.")
        elif irel is not None and irel < 1:
            item("Calote dos clientes", "bom", t)
        else:
            item("Calote dos clientes", "neutro", t)

    # 7. Resultado
    roe = g("roe")
    if roe is not None:
        if roe < 0:
            item("Lucro", "ruim" if roe < -0.1 else "atencao", f"Prejuízo nos últimos 12 meses (retorno sobre o patrimônio de {_p(roe)}). Prejuízo seguido consome o capital que protege os credores, incluindo quem tem CDB.")
        elif roe >= 0.12:
            item("Lucro", "bom", f"Lucro nos últimos 12 meses, com retorno sobre o patrimônio de {_p(roe)}.")
        else:
            item("Lucro", "neutro", f"Lucro nos últimos 12 meses, com retorno sobre o patrimônio de {_p(roe)}.")

    # 8. Notícias
    sn, graves = int(g("score_noticias") or 0), int(g("eventos_graves") or 0)
    if sn > 0 or graves > 0:
        item("Notícias recentes", "ruim" if graves else "atencao",
             f"O Quarto Pilar encontrou notícias negativas recentes sobre o banco ({graves} graves), que somam {sn} pontos ao score. Veja a página do banco.")

    ruins = sum(i["tom"] == "ruim" for i in itens)
    atenc = sum(i["tom"] == "atencao" for i in itens)
    bons = sum(i["tom"] == "bom" for i in itens)
    partes = []
    if ruins:
        partes.append(f"{ruins} {'ponto fraco' if ruins == 1 else 'pontos fracos'}")
    if atenc:
        partes.append(f"{atenc} {'ponto' if atenc == 1 else 'pontos'} de atenção")
    if bons:
        partes.append(f"{bons} {'ponto favorável' if bons == 1 else 'pontos favoráveis'}")
    resumo = f"No balanço de {_tri(l['anomes'])}: " + (", ".join(partes) if partes else "nenhum ponto fora do comum") + "."
    ordem = {"ruim": 0, "atencao": 1, "neutro": 2, "bom": 3}
    return {"resumo": resumo, "itens": sorted(itens, key=lambda i: ordem[i["tom"]])}


def montar(atual: pd.DataFrame, nomes: dict, liquidadas: set, tipos: dict,
           scores: pd.DataFrame | None = None, dossies: dict | None = None) -> dict:
    mensal = _cdi_mensal()
    ref = int(atual["anomes"].max())
    cdi_ref = cdi_12m(ref, mensal)
    idx = scores.set_index(["cod", "anomes"]) if scores is not None else None
    dossies = dossies or {}
    bancos = []
    for _, l in atual.iterrows():
        a, m = divmod(int(l["anomes"]), 100)
        antes = None
        if idx is not None and (l["cod"], (a - 1) * 100 + m) in idx.index:
            antes = idx.loc[(l["cod"], (a - 1) * 100 + m)]
            if isinstance(antes, pd.DataFrame):
                antes = antes.iloc[-1]
        regras = {s.get("regra") for s in (l.get("sinais") or [])}
        analise = analisar(l, antes, cdi_12m(int(l["anomes"]), mensal), regras)
        ia = dossies.get(l["cod"]) or {}
        if ia.get("resumo"):
            analise["ia"] = ia["resumo"]
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
            "analise": analise,
        })
    return {"anomes_ref": ref, "cdi_12m": cdi_ref, "bancos": bancos}
