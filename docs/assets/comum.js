// Funções compartilhadas pelas páginas do Quarto Pilar
const R = {
  cores: { normal: "#30d158", atencao: "#ffd60a", alerta: "#ff9f0a", alto: "#ff453a", azul: "#0a84ff", cinza: "rgba(235,235,245,.45)" },
  async json(caminho) {
    const r = await fetch(caminho, { cache: "no-cache" });
    if (!r.ok) throw new Error(`Falha ao carregar ${caminho}`);
    return r.json();
  },
  pct(v, casas = 1) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return (v * 100).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + "%";
  },
  bi(v) {
    if (v === null || v === undefined) return "—";
    if (v >= 1e12) return "R$ " + (v / 1e12).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + " tri";
    return "R$ " + (v / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " bi";
  },
  trimestre(anomes) {
    const a = String(anomes);
    const m = { "03": "mar", "06": "jun", "09": "set", "12": "dez" }[a.slice(4)];
    return `${m}/${a.slice(2, 4)}`;
  },
  classeNivel(n) {
    return { "Normal": "normal", "Atenção": "atencao", "Alerta": "alerta", "Alerta alto": "alto" }[n] || "normal";
  },
  corNivel(n) { return R.cores[R.classeNivel(n)]; },
  esc(t) {
    return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },
  dataHora(iso) {
    return new Date(iso).toLocaleString("pt-BR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" });
  },
  sparkline(valores, cor) {
    const v = valores.filter((x) => x !== null && x !== undefined);
    if (v.length < 2) return "";
    const w = 70, h = 30, max = 100, min = 0;
    const pts = v.map((y, i) => `${(i / (v.length - 1)) * w},${h - 2 - ((y - min) / (max - min)) * (h - 4)}`).join(" ");
    const base = h - 2 - (45 / 100) * (h - 4);
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2="${w}" y1="${base}" y2="${base}" stroke="rgba(235,235,245,.25)" stroke-dasharray="2 2" stroke-width="1"/>
      <polyline points="${pts}" fill="none" stroke="${cor}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  },
};
