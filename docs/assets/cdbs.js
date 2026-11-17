// Página de CDBs do Quarto Pilar
(async () => {
  let d;
  try {
    d = await R.json("data/cdbs.json");
  } catch (e) {
    document.getElementById("tabela").innerHTML = '<div class="vazio">Não foi possível carregar os dados.</div>';
    return;
  }
  const ativos = d.bancos.filter((b) => !b.liquidada);
  const temCdi = d.cdi_12m !== null && d.cdi_12m !== undefined;
  const caro = (b) => b.custo_pares !== null && b.custo_pares >= 1.25;
  const emAlerta = (b) => b.nivel === "Alerta" || b.nivel === "Alerta alto";
  const vezes = (v) => (v === null || v === undefined ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "x");
  const pctCdi = (v) => (v === null || v === undefined ? "—" : Math.round(v * 100) + "%");
  const classeX = (v) => (v === null ? "" : v >= 1.5 ? "v-alto" : v >= 1.25 ? "v-medio" : "");
  const sinalPct = (v) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + R.pct(v, 0));

  // ---------- resumo ----------
  const kpis = [
    temCdi ? [R.pct(d.cdi_12m), `CDI acumulado em 12 meses até ${R.trimestre(d.anomes_ref)}`]
           : [R.trimestre(d.anomes_ref), "balanço mais recente do Banco Central"],
    [ativos.filter(caro).length, "pagam 1,25x ou mais que os pares para captar"],
    [ativos.filter((b) => caro(b) && emAlerta(b)).length, "pagam caro e estão em alerta no Quarto Pilar"],
    [ativos.filter((b) => b.dep_prazo !== null && b.dep_prazo > 0.7).length, "têm mais de 70% da captação em CDB"],
  ];
  document.getElementById("kpis").innerHTML = kpis.map(([v, r]) =>
    `<div class="kpi"><div class="v">${v}</div><div class="r">${r}</div></div>`).join("");

  const ref = d.bancos.filter((b) => b.liquidada && b.custo_pares).sort((a, b) => b.custo_pares - a.custo_pares)[0];
  if (ref) {
    const el = document.getElementById("referencia");
    el.hidden = false;
    el.innerHTML = `<b>Para comparar:</b> no último balanço antes da liquidação (${R.trimestre(ref.anomes)}), o ${R.esc(ref.nome)} pagava ` +
      `${R.pct(ref.custo)} ao ano para captar${ref.custo_cdi ? `, ${pctCdi(ref.custo_cdi)} do CDI,` : ""} ${vezes(ref.custo_pares)} a mediana dos pares, ` +
      `com ${R.pct(ref.dep_prazo, 0)} da captação em CDB.`;
  }

  // ---------- tabela ----------
  const cols = [
    { k: "nome", t: "Banco", txt: true },
    { k: "score", t: "Score" },
    { k: "custo", t: "Custo de captação" },
    ...(temCdi ? [{ k: "custo_cdi", t: "% do CDI" }] : []),
    { k: "custo_pares", t: "x pares" },
    { k: "dep_prazo", t: "Em CDB" },
    { k: "cresc_captacoes", t: "Captação 12m" },
    { k: "cresc_carteira", t: "Carteira 12m" },
    { k: "liquidez", t: "Liquidez" },
  ];
  let ordem = { k: "custo_pares", asc: false };
  let filtro = "todos";
  let busca = "";
  const norm = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  function linhas() {
    let v = ativos;
    if (filtro === "caro") v = v.filter(caro);
    if (filtro === "acelerada") v = v.filter((b) => b.acelerada);
    if (filtro === "alerta") v = v.filter(emAlerta);
    if (busca) v = v.filter((b) => norm(b.nome).includes(busca));
    const { k, asc } = ordem;
    return [...v].sort((a, b) => {
      const x = a[k], y = b[k];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const c = typeof x === "string" ? x.localeCompare(y, "pt-BR") : x - y;
      return asc ? c : -c;
    });
  }

  function celula(b, k) {
    switch (k) {
      case "nome": {
        // o custo já aparece nas colunas; mostra o outro sinal mais forte ligado a quem compra CDB
        const s = b.sinais.find((t) => !/^Custo de captação/i.test(t));
        return `<div class="nome"><span class="seta" aria-hidden="true"></span>${R.esc(b.nome)}</div><div class="tipo">${R.esc(b.tipo)}</div>` +
          (s && (caro(b) || emAlerta(b)) ? `<div class="sinal">${R.esc(s)}</div>` : "");
      }
      case "score": return `<span class="pilula c-${R.classeNivel(b.nivel)}" title="${R.esc(b.nivel)}">${b.score}</span>`;
      case "custo": return R.pct(b.custo);
      case "custo_cdi": return pctCdi(b.custo_cdi);
      case "custo_pares": return `<span class="${classeX(b.custo_pares)}">${vezes(b.custo_pares)}</span>`;
      case "dep_prazo": return R.pct(b.dep_prazo, 0);
      case "cresc_captacoes": return `<span class="${b.acelerada ? "v-medio" : ""}">${sinalPct(b.cresc_captacoes)}</span>`;
      case "cresc_carteira": return sinalPct(b.cresc_carteira);
      case "liquidez": return R.pct(b.liquidez);
    }
    return "";
  }

  const abertos = new Set();
  const TOM = { ruim: "Ponto fraco", atencao: "Atenção", neutro: "Neutro", bom: "Favorável" };
  function dossie(b) {
    const a = b.analise || { itens: [] };
    const itens = a.itens.map((i) => `<li class="tom-${i.tom}"><div class="it-topo"><span class="bolinha"></span><b>${R.esc(i.titulo)}</b><span class="tom">${TOM[i.tom]}</span></div><p>${R.esc(i.texto)}</p></li>`).join("");
    return `<div class="dossie-box">
      <div class="dossie-cab"><span class="rotulo">Dossiê para quem compra CDB</span><span class="resumo">${R.esc(a.resumo || "")}</span></div>
      ${a.ia ? `<p class="dossie-ia"><span class="rotulo">Análise geral do banco (IA)</span>${R.esc(a.ia)}</p>` : ""}
      <ul class="dossie-itens">${itens}</ul>
      <div class="dossie-pe"><a href="index.html#${R.esc(b.cod)}">Abrir a página completa do banco →</a><span>Gerado automaticamente a partir do balanço entregue ao Banco Central. Não é recomendação.</span></div>
    </div>`;
  }

  function desenhar() {
    const v = linhas();
    const cab = cols.map((c) =>
      `<th><button data-k="${c.k}" class="${ordem.k === c.k ? "ord" + (ordem.asc ? " asc" : "") : ""}">${c.t}</button></th>`).join("");
    const corpo = v.length ? v.map((b) => {
      const ab = abertos.has(b.cod);
      return `<tr class="linha${ab ? " aberta" : ""}" data-cod="${R.esc(b.cod)}" aria-expanded="${ab}">${cols.map((c) => `<td>${celula(b, c.k)}</td>`).join("")}</tr>` +
        (ab ? `<tr class="dossie-cdb"><td colspan="${cols.length}">${dossie(b)}</td></tr>` : "");
    }).join("")
      : `<tr><td colspan="${cols.length}"><div class="vazio">Nenhum banco neste filtro.</div></td></tr>`;
    document.getElementById("tabela").innerHTML = `<table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table>`;
    document.getElementById("nota").textContent =
      `${v.length} de ${ativos.length} instituições · balanço de ${R.trimestre(d.anomes_ref)} · clique num banco para abrir o dossiê.`;
  }

  document.getElementById("tabela").addEventListener("click", (e) => {
    const b = e.target.closest("thead button");
    if (b) {
      const k = b.dataset.k;
      ordem = ordem.k === k ? { k, asc: !ordem.asc } : { k, asc: k === "nome" };
      desenhar();
      return;
    }
    if (e.target.closest(".dossie-cdb")) return;
    const tr = e.target.closest("tbody tr[data-cod]");
    if (!tr) return;
    const cod = tr.dataset.cod;
    abertos.has(cod) ? abertos.delete(cod) : abertos.add(cod);
    desenhar();
  });
  document.querySelectorAll(".segmentado button").forEach((b) => b.addEventListener("click", () => {
    filtro = b.dataset.f;
    document.querySelectorAll(".segmentado button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    desenhar();
  }));
  document.getElementById("busca").addEventListener("input", (e) => { busca = norm(e.target.value.trim()); desenhar(); });
  desenhar();

})();
