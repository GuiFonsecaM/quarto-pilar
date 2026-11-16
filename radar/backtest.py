"""Backtest: o score teria acendido antes das quebras conhecidas?

Quebras são detectadas no cadastro do IF.Data (instituição que passa de "A" para
"LE" = liquidação extrajudicial) e complementadas por config/eventos_conhecidos.csv.
A data em que um trimestre fica público é aproximada como fim do trimestre + 60 dias
(+90 dias para dezembro), igual ao calendário de divulgação do IF.Data.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import config as C


def publicacao(anomes: int) -> date:
    ano, mes = divmod(int(anomes), 100)
    fim = date(ano, mes, 30 if mes in (6, 9) else 31)
    return fim + timedelta(days=90 if mes == 12 else 60)


def _fim(anomes: int) -> date:
    ano, mes = divmod(int(anomes), 100)
    return date(ano, mes, 30 if mes in (6, 9) else 31)


def detectar_quebras(cadastro: pd.DataFrame) -> pd.DataFrame:
    c = cadastro.sort_values("AnoMes")
    out = []
    for cod, g in c.groupby("CodInst"):
        a, le = g[g["Situacao"] == "A"], g[g["Situacao"] == "LE"]
        if a.empty or le.empty:
            continue
        t = int(le["AnoMes"].min())
        antes = a[a["AnoMes"] < t]
        if antes.empty:
            continue
        ult = antes.iloc[-1]
        pru = ult["CodConglomeradoPrudencial"]
        pru = pru if isinstance(pru, str) and pru.startswith("C") else cod
        out.append({"cod": pru, "instituicao": ult["NomeInstituicao"], "data_evento": _fim(t),
                    "fonte": "cadastro IF.Data (situação LE)"})
    d = pd.DataFrame(out, columns=["cod", "instituicao", "data_evento", "fonte"])
    conhecidos = C.CONFIG / "eventos_conhecidos.csv"
    if conhecidos.exists():
        k = pd.read_csv(conhecidos, dtype=str)
        k["data_evento"] = pd.to_datetime(k["data_evento"]).dt.date
        k["fonte"] = k.get("fonte", "lista manual")
        d = pd.concat([k[["cod", "instituicao", "data_evento", "fonte"]], d], ignore_index=True)
    # um evento por conglomerado: o primeiro
    return d.sort_values("data_evento").drop_duplicates("cod").reset_index(drop=True)


def rodar(scores: pd.DataFrame, cadastro: pd.DataFrame) -> dict:
    ev = detectar_quebras(cadastro)
    ev = ev[ev["cod"].isin(set(scores["cod"]))]
    casos = []
    falhas = set(ev["cod"])
    for _, e in ev.iterrows():
        s = scores[(scores["cod"] == e["cod"])].copy()
        s["pub"] = s["anomes"].map(publicacao)
        s = s[s["pub"] <= e["data_evento"]].sort_values("anomes")
        if s.empty:
            continue
        janela = s.tail(12)
        serie = [{"anomes": int(r.anomes), "score": int(r.score_dados), "nivel": r.nivel}
                 for r in janela.itertuples()]
        alertas = janela[janela["score_dados"] >= 45]
        primeiro = alertas.iloc[0] if not alertas.empty else None
        casos.append({
            "cod": e["cod"],
            "nome": str(s["nome"].iloc[-1]),
            "data_evento": e["data_evento"].isoformat(),
            "fonte": e["fonte"],
            "ultimo_score": int(janela["score_dados"].iloc[-1]),
            "ultimo_nivel": janela["nivel"].iloc[-1],
            "primeiro_alerta": int(primeiro["anomes"]) if primeiro is not None else None,
            "antecedencia_meses": round((e["data_evento"] - publicacao(primeiro["anomes"])).days / 30.4)
            if primeiro is not None else None,
            "sinais_ultimo": janela["sinais"].iloc[-1][:5],
            "serie": serie,
        })
    # taxa de alertas entre bancos que não quebraram (proxy de falso positivo)
    vivos = scores[~scores["cod"].isin(falhas)]
    tx = vivos.groupby("anomes").apply(lambda t: (t["score_dados"] >= 45).mean(), include_groups=False)
    return {
        "casos": casos,
        "detectados": sum(1 for c in casos if c["primeiro_alerta"]),
        "total": len(casos),
        "taxa_alerta_sobreviventes": round(float(tx.tail(12).mean()), 4) if len(tx) else None,
    }


def markdown(res: dict) -> str:
    linhas = ["# Backtest do Quarto Pilar", "",
              f"Quebras no universo monitorado: **{res['total']}**. "
              f"Com alerta (score ≥ 45) antes do evento: **{res['detectados']}**.",
              f"Bancos que não quebraram e estavam em alerta (média dos últimos 12 trimestres): "
              f"**{(res['taxa_alerta_sobreviventes'] or 0) * 100:.1f}%**.", "",
              "| Banco | Evento | 1º alerta (trimestre) | Antecedência | Último score |",
              "|---|---|---|---|---|"]
    for c in res["casos"]:
        ant = f"{c['antecedencia_meses']} meses" if c["antecedencia_meses"] is not None else "—"
        pa = str(c["primeiro_alerta"] or "não alertou")
        linhas.append(f"| {c['nome']} | {c['data_evento']} | {pa} | {ant} | {c['ultimo_score']} ({c['ultimo_nivel']}) |")
    return "\n".join(linhas) + "\n"
