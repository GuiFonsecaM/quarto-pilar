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
  const brl = (v) => "R$ " + Math.round(v).toLocaleString("pt-BR");
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
        return `<div class="nome">${R.esc(b.nome)}</div><div class="tipo">${R.esc(b.tipo)}</div>` +
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

  function desenhar() {
    const v = linhas();
    const cab = cols.map((c) =>
      `<th><button data-k="${c.k}" class="${ordem.k === c.k ? "ord" + (ordem.asc ? " asc" : "") : ""}">${c.t}</button></th>`).join("");
    const corpo = v.length ? v.map((b) =>
      `<tr data-cod="${R.esc(b.cod)}">${cols.map((c) => `<td>${celula(b, c.k)}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${cols.length}"><div class="vazio">Nenhum banco neste filtro.</div></td></tr>`;
    document.getElementById("tabela").innerHTML = `<table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table>`;
    document.getElementById("nota").textContent =
      `${v.length} de ${ativos.length} instituições · balanço de ${R.trimestre(d.anomes_ref)} · clique numa linha para ver o banco completo.`;
  }

  document.getElementById("tabela").addEventListener("click", (e) => {
    const b = e.target.closest("thead button");
    if (b) {
      const k = b.dataset.k;
      ordem = ordem.k === k ? { k, asc: !ordem.asc } : { k, asc: k === "nome" };
      desenhar();
      return;
    }
    const tr = e.target.closest("tbody tr[data-cod]");
    if (tr) location.href = "index.html#" + tr.dataset.cod;
  });
  document.querySelectorAll(".segmentado button").forEach((b) => b.addEventListener("click", () => {
    filtro = b.dataset.f;
    document.querySelectorAll(".segmentado button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    desenhar();
  }));
  document.getElementById("busca").addEventListener("input", (e) => { busca = norm(e.target.value.trim()); desenhar(); });
  desenhar();

  // ---------- calculadora do FGC ----------
  const LIM = d.fgc_por_conglomerado, TETO = d.fgc_teto_4_anos;
  const porNome = new Map(ativos.map((b) => [norm(b.nome), b]));
  const lista = document.createElement("datalist");
  lista.id = "bancos-lista";
  lista.innerHTML = ativos.map((b) => `<option value="${R.esc(b.nome)}">`).join("");
  document.body.appendChild(lista);

  const guardar = (v) => { try { localStorage.setItem("qp_fgc", JSON.stringify(v)); } catch (e) { /* sem armazenamento */ } };
  const ler = () => { try { return JSON.parse(localStorage.getItem("qp_fgc")) || null; } catch (e) { return null; } };
  const valorNum = (t) => {
    const s = String(t).replace(/[^\d,]/g, "").replace(",", ".");
    const n = parseFloat(s);
    return Number.isFinite(n) ? n : 0;
  };
  const caixa = document.getElementById("linhas");

  function novaLinha(nome = "", valor = "") {
    const div = document.createElement("div");
    div.className = "fgc-linha";
    div.innerHTML = `<input class="banco" list="bancos-lista" placeholder="Banco (ex.: Banco Digimais)" aria-label="Banco" value="${R.esc(nome)}">
      <input class="valor" inputmode="decimal" placeholder="R$ 0" aria-label="Valor aplicado" value="${R.esc(valor)}">
      <button class="tirar" type="button" aria-label="Remover">×</button>`;
    caixa.appendChild(div);
  }

  function calcular() {
    const itens = [...caixa.querySelectorAll(".fgc-linha")].map((l) => ({
      nome: l.querySelector(".banco").value.trim(), valor: valorNum(l.querySelector(".valor").value),
    }));
    guardar(itens.map((i) => [i.nome, i.valor ? String(i.valor).replace(".", ",") : ""]));
    const grupos = new Map();
    for (const i of itens) {
      if (!i.valor) continue;
      const b = porNome.get(norm(i.nome));
      const chave = b ? b.cod : norm(i.nome) || "?";
      const g = grupos.get(chave) || { nome: b ? b.nome : (i.nome || "Sem nome"), banco: b, valor: 0 };
      g.valor += i.valor;
      grupos.set(chave, g);
    }
    const res = document.getElementById("resultado");
    if (!grupos.size) { res.innerHTML = ""; return; }
    let total = 0, coberto = 0, desc = 0, descAlerta = 0;
    const det = [...grupos.values()].map((g) => {
      const c = Math.min(g.valor, LIM), x = g.valor - c;
      total += g.valor; coberto += c; desc += x;
      if (g.banco && emAlerta(g.banco)) descAlerta += x;
      const pil = g.banco ? `<span class="pilula c-${R.classeNivel(g.banco.nivel)}" style="min-width:0;font-size:.78rem;padding:2px 7px;display:inline-block">${R.esc(g.banco.nivel)}</span>` : '<span class="cinza">—</span>';
      return `<tr><td>${R.esc(g.nome)}</td><td>${brl(g.valor)}</td><td>${brl(c)}</td><td class="${x ? "v-alto" : ""}">${brl(x)}</td><td>${pil}</td></tr>`;
    }).join("");
    const pc = total ? (coberto / total) * 100 : 0;
    const msgs = [];
    if (descAlerta > 0) msgs.push(`${brl(descAlerta)} ficam acima do limite em instituições que o Quarto Pilar marca como Alerta.`);
    if (coberto > TETO) msgs.push(`Se mais de um desses bancos quebrar dentro de 4 anos, o FGC paga no máximo ${brl(TETO)} no total.`);
    res.innerHTML = `<div class="fgc-res">
      <div class="fgc-barra" role="img" aria-label="${Math.round(pc)}% coberto pelo FGC"><div class="c" style="width:${pc}%"></div><div class="d" style="width:${100 - pc}%"></div></div>
      <div class="fgc-legenda"><span><i style="background:var(--verde)"></i>Coberto <b>${brl(coberto)}</b></span>
        <span><i style="background:var(--vermelho)"></i>Fora da garantia <b>${brl(desc)}</b></span>
        <span>Total <b>${brl(total)}</b></span></div>
      <table class="fgc-det"><thead><tr><th>Banco</th><th>Aplicado</th><th>Coberto</th><th>Fora</th><th>Quarto Pilar</th></tr></thead><tbody>${det}</tbody></table>
      ${msgs.map((m) => `<div class="fgc-msg">${m}</div>`).join("")}</div>`;
  }

  caixa.addEventListener("input", calcular);
  caixa.addEventListener("change", calcular);
  caixa.addEventListener("click", (e) => {
    if (!e.target.classList.contains("tirar")) return;
    e.target.closest(".fgc-linha").remove();
    if (!caixa.children.length) novaLinha();
    calcular();
  });
  document.getElementById("add").addEventListener("click", () => { novaLinha(); caixa.lastElementChild.querySelector(".banco").focus(); });
  const salvos = ler();
  if (salvos && salvos.length) salvos.forEach(([n, v]) => novaLinha(n, v)); else { novaLinha(); novaLinha(); }
  calcular();
})();
