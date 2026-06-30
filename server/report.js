// Genera un report HTML autocontenuto (stampabile in PDF dal browser).
// Funzionalità Premium: report scaricabile.

import { scoreMeta } from "./score.js";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

export function buildReportHtml(result) {
  const meta = scoreMeta(result.score);
  const date = new Date().toLocaleString("it-IT");
  const color =
    meta.level === "high" ? "#d6336c" : meta.level === "medium" ? "#e8910c" : "#2b9348";

  const breachRows = (result.breaches || [])
    .map(
      (b) => `<tr>
        <td><strong>${esc(b.title || b.name)}</strong>${b.year ? " · " + esc(b.year) : ""}</td>
        <td>${esc((b.dataClasses || []).join(", ") || "—")}</td>
        <td style="color:#d6336c;font-weight:600">TROVATA</td>
      </tr>`
    )
    .join("");

  const platformRows = (result.platforms || [])
    .map(
      (p) => `<tr>
        <td><strong>${esc(p.name)}</strong></td>
        <td><a href="${esc(p.url)}">${esc(p.url)}</a></td>
        <td style="color:${p.status === "exposed" ? "#d6336c" : "#2b9348"};font-weight:600">
          ${p.status === "exposed" ? "TROVATO" : p.status === "clear" ? "LIBERO" : "INCERTO"}
        </td>
      </tr>`
    )
    .join("");

  const section =
    result.mode === "email"
      ? `<h2>Data breach noti</h2>
         <table><thead><tr><th>Breach</th><th>Dati esposti</th><th>Esito</th></tr></thead>
         <tbody>${breachRows || `<tr><td colspan="3">Nessun breach trovato 🎉</td></tr>`}</tbody></table>`
      : `<h2>Presenza pubblica su piattaforme</h2>
         <table><thead><tr><th>Piattaforma</th><th>URL</th><th>Esito</th></tr></thead>
         <tbody>${platformRows}</tbody></table>`;

  return `<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<title>Report esposizione · ${esc(result.query)}</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; color:#1a2233; max-width:760px; margin:40px auto; padding:0 20px; }
  header { display:flex; align-items:center; gap:12px; border-bottom:2px solid #eee; padding-bottom:16px; }
  .logo { width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,#34e1c2,#4f8bff);display:grid;place-items:center;font-size:20px; }
  h1 { font-size:20px; margin:0; }
  .muted { color:#6b7794; font-size:13px; }
  .score { text-align:center; margin:28px 0; }
  .score .val { font-size:54px; font-weight:800; color:${color}; line-height:1; }
  .score .lab { font-weight:700; margin-top:6px; color:${color}; }
  .score .desc { color:#6b7794; max-width:480px; margin:8px auto 0; }
  table { width:100%; border-collapse:collapse; margin:10px 0 26px; font-size:14px; }
  th,td { text-align:left; padding:10px 8px; border-bottom:1px solid #eee; vertical-align:top; }
  th { color:#6b7794; font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  .note { background:#f4f7fb; border-radius:10px; padding:14px 16px; font-size:13px; color:#445; }
  footer { margin-top:30px; color:#9aa6c0; font-size:12px; text-align:center; }
</style></head>
<body>
  <header>
    <div class="logo">🛡️</div>
    <div>
      <h1>Report di esposizione digitale</h1>
      <div class="muted">Target: <strong>${esc(result.query)}</strong> · generato il ${esc(date)}</div>
    </div>
  </header>

  <div class="score">
    <div class="val">${result.score}<span style="font-size:20px;color:#6b7794">/100</span></div>
    <div class="lab">${esc(meta.label)}</div>
    <div class="desc">${esc(meta.desc)}</div>
  </div>

  ${section}

  <div class="note">
    <strong>Nota etica.</strong> Questo report riguarda la tua esposizione o quella
    di chi ha dato il consenso esplicito. Usalo per ridurre la tua superficie di
    attacco: cambia le password riutilizzate, attiva la 2FA, rimuovi gli account
    pubblici che non usi più.
    ${result.demo ? '<br><br><strong>⚠️ Dati dimostrativi:</strong> backend HIBP non configurato, i breach mostrati sono fittizi.' : ""}
  </div>

  <footer>FootprintChecker · self-check OSINT a scopo difensivo</footer>
</body></html>`;
}
