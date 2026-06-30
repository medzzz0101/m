// ---------------------------------------------------------------------------
// Footprint Checker — backend proxy (leggero, senza database).
//
// Ruolo: il frontend NON parla mai con le API esterne né conosce la chiave
// HIBP. Tutto passa di qui. Endpoint:
//   POST /api/scan/email     { email, consent }
//   POST /api/scan/username  { username, consent }
//   POST /api/report         { ...result }            (Premium: download HTML/PDF)
//   GET  /api/health
// Serve anche il frontend statico (index.html).
// ---------------------------------------------------------------------------

import "dotenv/config";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { checkEmailBreaches } from "./hibp.js";
import { checkUsername } from "./usernameCheck.js";
import { emailScore, usernameScore, scoreMeta } from "./score.js";
import { buildReportHtml } from "./report.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

const PORT = Number(process.env.PORT) || 3000;
const FREE_SCANS = Number(process.env.FREE_SCANS) || 2;
const HIBP_API_KEY = process.env.HIBP_API_KEY || "";
const HIBP_USER_AGENT = process.env.HIBP_USER_AGENT || "FootprintChecker-SelfCheck";

const app = express();
app.use(express.json({ limit: "256kb" }));

// --- Quota gratuita in-memory (niente DB all'inizio). Per visitatore (IP). ---
// Premium si simula con header `x-premium: 1` (in produzione: token/sessione).
const usage = new Map(); // ip -> count
function clientIp(req) {
  return (req.headers["x-forwarded-for"]?.split(",")[0] || req.ip || "anon").trim();
}
function isPremium(req) {
  return req.headers["x-premium"] === "1";
}
function quotaState(req) {
  const ip = clientIp(req);
  const used = usage.get(ip) || 0;
  return { ip, used, remaining: Math.max(0, FREE_SCANS - used), premium: isPremium(req) };
}
function consumeQuota(ip) {
  usage.set(ip, (usage.get(ip) || 0) + 1);
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function guard(req, res) {
  if (!req.body?.consent) {
    res.status(403).json({
      error:
        "Consenso richiesto: questo strumento controlla solo la TUA esposizione o quella di chi acconsente esplicitamente.",
    });
    return false;
  }
  const q = quotaState(req);
  if (!q.premium && q.remaining <= 0) {
    res.status(402).json({ error: "Scansioni gratuite esaurite.", remaining: 0, locked: true });
    return false;
  }
  return true;
}

// --------------------------- API: scan email -------------------------------
app.post("/api/scan/email", async (req, res) => {
  const email = String(req.body?.email || "").trim();
  if (!EMAIL_RE.test(email)) return res.status(400).json({ error: "Formato email non valido." });
  if (!guard(req, res)) return;

  const { demo, breaches, error } = await checkEmailBreaches(email, {
    apiKey: HIBP_API_KEY,
    userAgent: HIBP_USER_AGENT,
  });
  if (error) return res.status(502).json({ error });

  if (!isPremium(req)) consumeQuota(clientIp(req));
  const score = emailScore(breaches);
  res.json({
    mode: "email",
    query: email,
    demo,
    score,
    meta: scoreMeta(score),
    breaches,
    quota: quotaState(req),
  });
});

// ------------------------- API: scan username ------------------------------
app.post("/api/scan/username", async (req, res) => {
  const username = String(req.body?.username || "").trim();
  if (!username) return res.status(400).json({ error: "Inserisci uno username." });
  if (!guard(req, res)) return;

  const { platforms, error } = await checkUsername(username);
  if (error) return res.status(400).json({ error });

  if (!isPremium(req)) consumeQuota(clientIp(req));
  const score = usernameScore(platforms);
  res.json({
    mode: "username",
    query: username,
    demo: false,
    score,
    meta: scoreMeta(score),
    platforms,
    quota: quotaState(req),
  });
});

// --------------------- API: report scaricabile (Premium) -------------------
app.post("/api/report", (req, res) => {
  if (!isPremium(req)) {
    return res.status(402).json({ error: "Il report scaricabile è una funzione Premium." });
  }
  const r = req.body || {};
  if (!r.mode || !r.query) return res.status(400).json({ error: "Dati report mancanti." });

  const html = buildReportHtml(r);
  const safe = String(r.query).replace(/[^a-z0-9._-]/gi, "_").slice(0, 40);
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="footprint-report-${safe}.html"`);
  res.send(html);
});

// ------------------------------- health ------------------------------------
app.get("/api/health", (req, res) => {
  res.json({
    ok: true,
    hibpConfigured: Boolean(HIBP_API_KEY),
    freeScans: FREE_SCANS,
    quota: quotaState(req),
  });
});

// --------------------------- frontend statico ------------------------------
app.use(express.static(ROOT, { extensions: ["html"] }));
app.get("/", (req, res) => res.sendFile(path.join(ROOT, "index.html")));

app.listen(PORT, () => {
  console.log(`\n🛡️  Footprint Checker su http://localhost:${PORT}`);
  console.log(`    HIBP: ${HIBP_API_KEY ? "configurato ✅" : "NON configurato → modalità demo per le email ⚠️"}`);
  console.log(`    Scansioni gratuite per visitatore: ${FREE_SCANS}\n`);
});
