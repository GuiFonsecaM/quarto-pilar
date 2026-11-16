// App principal: lista de bancos à esquerda e detalhe à direita (estilo app Bolsa)
const estado = { dados: [], filtro: "todos", busca: "", sel: null, grafico: null, metrica: "score", banco: null };
const desktop = () => matchMedia("(min-width: 861px)").matches;

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = "rgba(235,235,245,.6)";

const METRICAS = {
  score: { nome: "Score", pct: false, serie: (s) => [{ d: s.score, nome: "Score de dados" }], ref: { v: 45, nome: "Início do alerta" }, min: 0, max: 100 },
  basileia: { nome: "Basileia", serie: (s) => [{ d: s.basileia, nome: "Basileia" }, { d: s.basileia_pares, nome: "Pares", pares: true }], ref: { v: 0.105, nome: "Mínimo 10,5%" } },
  captacao: { nome: "Captação", serie: (s) => [{ d: s.cresc_captacoes, nome: "Captação 12m" }, { d: s.cresc_carteira, nome: "Carteira 12m", cor: "#0a84ff" }, { d: s.cresc_captacoes_pares, nome: "Captação dos pares", pares: true }] },
  custo: { nome: "Custo", serie: (s) => [{ d: s.custo, nome: "Custo de captação" }, { d: s.custo_pares, nome: "Pares", pares: true }] },
  liquidez: { nome: "Liquidez", serie: (s) => [{ d: s.liquidez, nome: "Liquidez imediata" }, { d: s.liquidez_pares, nome: "Pares", pares: true }] },
  ativos: { nome: "Ativos difíceis", serie: (s) => [{ d: s.ativos_outros, nome: "Ativos de difícil avaliação" }] },
  tamanho: { nome: "Tamanho", bi: true, serie: (s) => [{ d: s.ativo_total, nome: "Ativo total" }, { d: s.captacoes, nome: "Captação", cor: "#0a84ff" }] },
};

function semAcento(t) { return t.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase(); }

function desenharLista() {
  const q = semAcento(estado.busca);
  const itens = estado.dados.filter((b) => {
    if (q && !semAcento(b.nome).includes(q)) return false;
    if (estado.filtro === "todos") return true;
    if (b.liquidada) return false;
    if (estado.filtro === "alerta") return b.nivel === "Alerta" || b.nivel === "Alerta alto";
    return b.nivel === estado.filtro;
  });
  document.getElementById("lista").innerHTML = itens.slice(0, 400).map((b) => {
    const c = b.liquidada ? "liq" : R.classeNivel(b.nivel);
    const cor = b.liquidada ? "#8e8e93" : R.corNivel(b.nivel);
    const varTxt = b.liquidada ? "liquidada" : b.variacao ? `${b.variacao > 0 ? "+" : ""}${b.variacao} no tri` : b.nivel;
    return `<div class="item${b.cod === estado.sel ? " sel" : ""}" role="listitem" tabindex="0" data-cod="${b.cod}">
      <div style="min-width:0"><div class="n1">${R.esc(b.nome)}</div><div class="n2">${R.esc(b.tipo)}</div></div>
      ${R.sparkline(b.spark || [], cor) || '<span aria-hidden="true"></span>'}
      <div class="pilula c-${c}">${b.score}<small>${varTxt}</small></div>
    </div>`;
  }).join("") + `<div class="rodape-lista">${itens.length} instituições · ativo acima de R$ 1 bi</div>`;
}

function graficoPrincipal(b) {
  const m = METRICAS[estado.metrica], s = b.serie;
  const cor = b.liquidada ? "#8e8e93" : R.corNivel(b.nivel);
  const fmt = (v) => m.bi ? R.bi(v) : m.pct === false ? Math.round(v) : R.pct(v);
  if (estado.grafico) estado.grafico.destroy();
  const ctx = document.getElementById("g").getContext("2d");
  const datasets = m.serie(s).map((x, i) => {
    const c = x.pares ? "rgba(235,235,245,.45)" : (x.cor || cor);
    return {
      label: x.nome, data: x.d, borderColor: c, borderWidth: x.pares ? 1.5 : 2.2, borderDash: x.pares ? [4, 4] : [],
      pointRadius: 0, pointHoverRadius: 4, tension: 0.3, spanGaps: true,
      fill: i === 0 ? "start" : false,
      backgroundColor: i === 0 ? (cc) => {
        const { chartArea } = cc.chart; if (!chartArea) return "transparent";
        const g = cc.chart.ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        g.addColorStop(0, c + "55"); g.addColorStop(1, c + "00"); return g;
      } : c,
    };
  });
  if (m.ref) datasets.push({ label: m.ref.nome, data: s.anomes.map(() => m.ref.v), borderColor: "#ff453a", borderWidth: 1, borderDash: [2, 3], pointRadius: 0, fill: false });
  estado.grafico = new Chart(ctx, {
    type: "line",
    data: { labels: s.anomes.map(R.trimestre), datasets },
    options: {
      maintainAspectRatio: false, animation: { duration: 350 },
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: "#2c2c2e", padding: 10, displayColors: false,
        callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y === null ? "—" : fmt(c.parsed.y)}` } } },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
        y: { position: "right", min: m.min, max: m.max, grid: { color: "rgba(84,84,88,.35)" }, border: { display: false },
          ticks: { maxTicksLimit: 5, callback: (v) => fmt(v) } },
      },
    },
  });
  document.getElementById("legenda").innerHTML = datasets.map((d) =>
    `<span><i style="border-color:${d.borderColor};${d.borderDash.length ? "border-top-style:dashed" : ""}"></i>${R.esc(d.label)}</span>`).join("");
}

// Evidências: F = dado do Banco Central, N = notícia. Mostradas com nomes legíveis.
function rotuloEv(id, d) {
  const n = id.slice(1);
  if (id[0] === "N") {
    const x = (d.noticias || []).find((y) => y.id === id);
    return `Notícia ${n}${x && x.fonte ? " · " + x.fonte : ""}`;
  }
  return `Dado ${n} do BC`;
}
// Explicação de cada indicador do quadro (botão "i")
const EXPLICA = {
  "Score de dados": "Nota de alerta de 0 a 100 calculada só com o balanço do Banco Central. Quanto maior, mais sinais de risco. Até 24 é Normal, de 25 a 44 Atenção, de 45 a 64 Alerta e de 65 para cima Alerta alto.",
  "Notícias": "Pontos somados por notícias negativas dos últimos 45 dias, como liquidação, fraude ou atraso de pagamento. Vai de 0 a +30 e perde peso com o tempo.",
  "Pares": "Grupo usado na comparação: o segmento do banco na classificação do Banco Central, de S1 (os maiores) a S5 (os menores).",
  "Basileia": "Capital próprio do banco para cada R$ 100 de risco que ele assume. A referência geral é 10,5%. Abaixo disso, ele tem pouca reserva para absorver perdas.",
  "Capital principal": "A parte mais sólida do capital: dinheiro dos sócios e lucros guardados. O traço quer dizer que o banco não informou, o que é comum em instituições pequenas.",
  "ROE 12m": "Lucro dos últimos 12 meses dividido pelo patrimônio. Negativo significa prejuízo. Quanto mais negativo, mais o banco consumiu do próprio capital.",
  "Ativo": "Tamanho do banco: tudo o que ele tem, como empréstimos, títulos e dinheiro em caixa.",
  "Captação 12m": "Quanto o dinheiro captado (CDB e depósitos) cresceu ou caiu em 12 meses. Crescimento muito rápido ou queda forte merecem atenção.",
  "Carteira 12m": "Quanto os empréstimos do banco cresceram ou caíram em 12 meses. Se a captação cresce muito mais que a carteira, o dinheiro está indo para outro lugar.",
  "Custo captação": "Quanto o banco paga por ano, em média, pelo dinheiro que capta. Bem acima dos pares indica que ele precisa pagar caro para atrair dinheiro, como acontecia com o Master.",
  "Liquidez": "Dinheiro disponível na hora para cada R$ 100 captados. Muito baixo, perto de 2%, deixa o banco sem folga se muitos clientes resgatarem ao mesmo tempo.",
  "Ativos difíceis": "Parte do ativo que não é caixa, título público nem empréstimo comum, como precatórios e direitos creditórios. São itens difíceis de avaliar e de vender rápido.",
};
function st(rotulo, valor) {
  return `<div><span>${rotulo}<button class="info" data-info="${rotulo}" aria-label="O que é ${rotulo}?">i</button></span><b>${valor}</b></div>`;
}
function mostrarInfo(btn) {
  const pop = document.getElementById("popover"), det = btn.closest(".det");
  if (!pop.hidden && pop.dataset.de === btn.dataset.info) { pop.hidden = true; return; }
  pop.innerHTML = `<b>${R.esc(btn.dataset.info)}</b><p>${R.esc(EXPLICA[btn.dataset.info] || "")}</p>`;
  pop.dataset.de = btn.dataset.info;
  pop.hidden = false;
  const rb = btn.getBoundingClientRect(), rd = det.getBoundingClientRect();
  const largura = pop.offsetWidth;
  pop.style.top = `${rb.bottom - rd.top + 8}px`;
  pop.style.left = `${Math.max(8, Math.min(rb.left - rd.left - 12, rd.width - largura - 8))}px`;
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".info");
  if (btn) { e.stopPropagation(); mostrarInfo(btn); return; }
  const pop = document.getElementById("popover");
  if (pop && !pop.hidden && !e.target.closest(".popover")) pop.hidden = true;
});
document.addEventListener("keydown", (e) => {
  const pop = document.getElementById("popover");
  if (e.key === "Escape" && pop) pop.hidden = true;
});

function evid(id, d) {
  const f = [...(d.fatos || []), ...(d.noticias || [])].find((x) => x.id === id);
  return f ? `<button class="ev" title="${R.esc(f.texto)}">${R.esc(rotuloEv(id, d))}</button>` : "";
}

async function abrir(cod, empurrar = true) {
  estado.sel = cod;
  document.querySelectorAll(".item").forEach((el) => el.classList.toggle("sel", el.dataset.cod === cod));
  if (empurrar) history.replaceState(null, "", "#" + cod);
  const box = document.getElementById("detalhe");
  let b;
  try { b = await R.json(`data/bancos/${encodeURIComponent(cod)}.json`); }
  catch { box.innerHTML = '<div class="boas-vindas">Instituição não encontrada.</div>'; return; }
  estado.banco = b;
  document.getElementById("app").classList.add("aberto");
  document.title = `${b.nome} · Quarto Pilar`;
  const s = b.serie, ult = (k) => s[k][s[k].length - 1];
  const sc = s.score.filter((x) => x !== null);
  const delta = sc.length > 1 ? sc[sc.length - 1] - sc[sc.length - 2] : null;
  const corDelta = delta > 0 ? "vermelho" : delta < 0 ? "verde" : "cinza";
  const c = b.liquidada ? "liq" : R.classeNivel(b.nivel);
  const d = b.dossie;
  const lista = (itens) => itens.map((p) => `<li>${R.esc(p.texto)}${p.evidencias.map((e) => evid(e, d)).join("")}</li>`).join("");
  const corGrav = ["#636366", "#ffd60a", "#ff9f0a", "#ff453a"];

  box.innerHTML = `<div class="det">
    <button class="voltar" id="voltar">‹ Bancos</button>
    <h1>${R.esc(b.nome)}</h1>
    <div class="sub">${R.esc(b.tipo)}${b.segmento ? " · " + b.segmento : ""} · ${R.esc(b.nome_oficial || "")}</div>
    <div class="preco">
      <span class="v">${b.score_final}<small> /100 de alerta</small></span>
      <span class="etq c-${c}">${b.liquidada ? "Em liquidação" : b.nivel}</span>
      ${delta !== null ? `<span class="var ${corDelta}">${delta > 0 ? "+" : ""}${delta} desde ${R.trimestre(s.anomes[s.anomes.length - 2])}</span>` : ""}
    </div>
    <div class="sub">Quanto maior, mais sinais de risco · balanço de ${R.trimestre(b.anomes_ref)}${b.score_noticias ? ` · +${b.score_noticias} por notícias recentes` : ""}</div>
    ${b.liquidada ? '<div class="aviso forte">Esta instituição entrou em liquidação extrajudicial. Os números são os últimos divulgados antes do evento.</div>'
      : b.defasado ? `<div class="aviso forte">Não divulgou a data-base mais recente. Números de ${R.trimestre(b.anomes_ref)}.</div>` : ""}

    <div class="metricas" role="group" aria-label="Indicador do gráfico">
      ${Object.entries(METRICAS).map(([k, m]) => `<button data-m="${k}" aria-pressed="${k === estado.metrica}">${m.nome}</button>`).join("")}
    </div>
    <div class="grafico-principal"><canvas id="g"></canvas></div>
    <div class="legenda" id="legenda"></div>

    <div class="stats">
      ${st("Score de dados", b.score_dados)}
      ${st("Notícias", "+" + b.score_noticias)}
      ${st("Pares", R.esc(b.grupo_pares || "—"))}
      ${st("Basileia", R.pct(ult("basileia")))}
      ${st("Capital principal", R.pct(ult("indice_cp")))}
      ${st("ROE 12m", R.pct(ult("roe")))}
      ${st("Ativo", R.bi(ult("ativo_total")))}
      ${st("Captação 12m", R.pct(ult("cresc_captacoes")))}
      ${st("Carteira 12m", R.pct(ult("cresc_carteira")))}
      ${st("Custo captação", R.pct(ult("custo")))}
      ${st("Liquidez", R.pct(ult("liquidez")))}
      ${st("Ativos difíceis", R.pct(ult("ativos_outros")))}
    </div>
    <div class="popover" id="popover" role="dialog" hidden></div>


    <div class="bloco"><h2>Sinais</h2>
      <div class="cartao">${b.sinais.length ? b.sinais.map((x) => `<div class="linha-sinal"><span>${R.esc(x.texto)}</span><b>+${x.pontos}</b></div>`).join("")
        : '<div class="vazio">Nenhuma regra de alerta disparou neste trimestre.</div>'}</div></div>

    ${d ? `<div class="bloco"><h2>Dossiê</h2>
      <p class="desc">${d.metodo === "ia" ? "Escrito por IA usando só as fontes listadas no fim. Cada frase indica de onde veio; passe o mouse ou toque para ver." : "Resumo automático a partir das regras do Quarto Pilar."}</p>
      <div class="dossie">
        <p class="resumo">${R.esc(d.resumo)}</p>
        ${d.pontos.length ? `<h3>Por que está no radar</h3><ul>${lista(d.pontos)}</ul>` : ""}
        ${(d.contradicoes || []).length ? `<h3>O que não condiz</h3><ul>${lista(d.contradicoes)}</ul>` : ""}
        ${(d.acompanhar || []).length ? `<h3>O que acompanhar</h3><ul>${d.acompanhar.map((a) => `<li>${R.esc(a)}</li>`).join("")}</ul>` : ""}
        <h3>Fontes usadas</h3><ul class="fontes">${(d.fatos || []).map((f) => `<li><span class="ev">${R.esc(rotuloEv(f.id, d))}</span> ${R.esc(f.texto)}</li>`).join("")}
        ${(d.noticias || []).map((n) => `<li><span class="ev">${R.esc(rotuloEv(n.id, d))}</span> <a href="${R.esc(n.link)}" target="_blank" rel="noopener">${R.esc(n.texto)}</a></li>`).join("")}</ul>
        <div class="nota">Números da data-base ${R.trimestre(d.anomes)}.</div>
      </div></div>` : ""}

    ${(b.relacoes || []).length ? `<div class="bloco"><h2>Relacionamentos</h2>
      <p class="desc">Ligações com outras instituições citadas na imprensa: venda de carteiras, compras, aportes e fundos em comum.</p>
      <div class="cartao">${b.relacoes.map((r) => `<div class="relacao">
        <div class="rel-topo">${r.outro_cod ? `<a href="#${R.esc(r.outro_cod)}" data-abrir="${R.esc(r.outro_cod)}">${R.esc(r.outro)}</a>` : `<span>${R.esc(r.outro)}</span>`}
          <span class="rel-tag">${r.origem === "curadoria" ? "verificado" : "extraído de notícia"}</span></div>
        <div class="rel-desc">${R.esc(r.descricao)}</div>
        <div class="meta">${r.data ? r.data.split("-").reverse().join("/") + " · " : ""}${r.link ? `<a href="${R.esc(r.link)}" target="_blank" rel="noopener">${R.esc(r.fonte || "fonte")}</a>` : R.esc(r.fonte || "")}</div>
      </div>`).join("")}</div></div>` : ""}

    <div class="bloco"><h2>Notícias</h2>
      <div class="cartao">${b.noticias.length ? b.noticias.map((n) => `<a class="noticia" href="${R.esc(n.link)}" target="_blank" rel="noopener">
        <div class="fonte">${R.esc(n.fonte || "Notícia")}</div>
        <div class="tit">${R.esc(n.titulo)}</div>
        <div class="meta"><span class="ponto" style="background:${corGrav[n.gravidade] || corGrav[0]}"></span>${R.esc(n.tipo_label)} · ${n.data.split("-").reverse().join("/")}${n.metodo === "ia" ? " · classificado por IA" : ""}</div>
      </a>`).join("") : '<div class="vazio">Nenhuma notícia nos últimos 120 dias.</div>'}</div></div>

    <p class="aviso" style="margin-top:28px">Sinais estatísticos calculados com dados públicos do Banco Central. Não são avaliação de crédito, acusação ou recomendação de investimento. <a href="metodologia.html">Metodologia</a></p>
    <p class="assinatura">Criado por Guilherme Fonseca</p>
  </div>`;
  box.scrollTop = 0;
  graficoPrincipal(b);
  box.querySelectorAll("[data-m]").forEach((bt) => bt.addEventListener("click", () => {
    estado.metrica = bt.dataset.m;
    box.querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", String(x === bt)));
    graficoPrincipal(estado.banco);
  }));
  box.querySelectorAll("[data-abrir]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); abrir(a.dataset.abrir);
  }));
  document.getElementById("voltar").addEventListener("click", () => {
    document.getElementById("app").classList.remove("aberto");
    history.replaceState(null, "", location.pathname);
  });
}

(async () => {
  const [meta, ranking] = await Promise.all([R.json("data/meta.json"), R.json("data/ranking.json")]);
  estado.dados = ranking.sort((a, b) => (a.liquidada - b.liquidada) || (b.score - a.score));
  document.getElementById("data").textContent = `Atualizado em ${R.dataHora(meta.atualizado_em)}`;
  desenharLista();
  const inicial = location.hash.slice(1);
  if (inicial) abrir(inicial, false);
  else if (desktop() && estado.dados.length) abrir(estado.dados[0].cod);
})().catch((e) => {
  document.getElementById("detalhe").innerHTML = '<div class="boas-vindas">Não foi possível carregar os dados.</div>';
  console.error(e);
});

document.getElementById("lista").addEventListener("click", (e) => {
  const it = e.target.closest(".item"); if (it) abrir(it.dataset.cod);
});
document.getElementById("lista").addEventListener("keydown", (e) => {
  const it = e.target.closest(".item"); if (it && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); abrir(it.dataset.cod); }
});
document.getElementById("busca").addEventListener("input", (e) => { estado.busca = e.target.value; desenharLista(); });
document.querySelectorAll("[data-nivel]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("[data-nivel]").forEach((x) => x.setAttribute("aria-pressed", "false"));
  b.setAttribute("aria-pressed", "true"); estado.filtro = b.dataset.nivel; desenharLista();
}));
