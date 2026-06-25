// ---------------------------------------------------------------------------
// Username presence check, stile "Sherlock" (versione leggera).
//
// AMBITO ETICO: questo modulo verifica solo se un dato username ESISTE
// pubblicamente su una lista curata di piattaforme. È pensato per il
// self-check (controllo la MIA esposizione) o con consenso esplicito.
// Niente enumerazione di massa, niente scraping di dati personali: leggiamo
// solo lo status della pagina profilo pubblica.
// ---------------------------------------------------------------------------

// Per ogni piattaforma definiamo come capire se l'username esiste.
//  - method "status": esiste se lo status code è in `existCodes`.
//  - method "body":   esiste se lo status è 200 e il body NON contiene `absentText`.
const PLATFORMS = [
  { name: "GitHub", icon: "🐙", url: "https://github.com/{u}", method: "status", existCodes: [200], absentCodes: [404] },
  { name: "Reddit", icon: "👽", url: "https://www.reddit.com/user/{u}/about.json", method: "status", existCodes: [200], absentCodes: [404] },
  { name: "Instagram", icon: "📸", url: "https://www.instagram.com/{u}/", method: "status", existCodes: [200], absentCodes: [404] },
  { name: "TikTok", icon: "🎵", url: "https://www.tiktok.com/@{u}", method: "body", absentText: "couldn't find this account" },
  { name: "GitLab", icon: "🦊", url: "https://gitlab.com/{u}", method: "status", existCodes: [200], absentCodes: [404] },
  { name: "Steam", icon: "🎮", url: "https://steamcommunity.com/id/{u}", method: "body", absentText: "The specified profile could not be found" },
  { name: "Telegram", icon: "✈️", url: "https://t.me/{u}", method: "body", absentText: "If you have Telegram, you can contact" },
  { name: "Twitch", icon: "🟣", url: "https://m.twitch.tv/{u}", method: "status", existCodes: [200], absentCodes: [404] },
];

const DEFAULT_TIMEOUT = 6000;
const UA =
  "Mozilla/5.0 (compatible; FootprintChecker-SelfCheck/0.2; +self-exposure-check)";

function isValidUsername(u) {
  return typeof u === "string" && /^[A-Za-z0-9._-]{1,40}$/.test(u);
}

async function checkOne(platform, username) {
  const url = platform.url.replace("{u}", encodeURIComponent(username));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  const base = { name: platform.name, icon: platform.icon, url };

  try {
    const res = await fetch(url, {
      method: platform.method === "body" ? "GET" : "GET",
      redirect: "manual",
      signal: controller.signal,
      headers: { "user-agent": UA, accept: "text/html,application/json" },
    });

    if (platform.method === "status") {
      if (platform.existCodes.includes(res.status)) return { ...base, status: "exposed" };
      if (platform.absentCodes?.includes(res.status)) return { ...base, status: "clear" };
      // redirect spesso = profilo assente o login wall
      if (res.status >= 300 && res.status < 400) return { ...base, status: "clear" };
      return { ...base, status: "unknown" };
    }

    // method "body"
    if (res.status === 404) return { ...base, status: "clear" };
    const text = await res.text();
    if (platform.absentText && text.includes(platform.absentText)) {
      return { ...base, status: "clear" };
    }
    return { ...base, status: res.status === 200 ? "exposed" : "unknown" };
  } catch (err) {
    return { ...base, status: "unknown", note: err.name === "AbortError" ? "timeout" : "errore" };
  } finally {
    clearTimeout(timer);
  }
}

/** Esegue i check con un limite di concorrenza. */
async function runWithConcurrency(tasks, limit = 5) {
  const results = [];
  let i = 0;
  async function worker() {
    while (i < tasks.length) {
      const idx = i++;
      results[idx] = await tasks[idx]();
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker));
  return results;
}

/**
 * Controlla la presenza pubblica di uno username sulle piattaforme note.
 * @returns {Promise<{platforms:Array, error?:string}>}
 */
export async function checkUsername(username) {
  if (!isValidUsername(username)) {
    return { platforms: [], error: "Username non valido (usa lettere, numeri, . _ -)." };
  }
  const tasks = PLATFORMS.map((p) => () => checkOne(p, username));
  const platforms = await runWithConcurrency(tasks, 5);
  return { platforms };
}

export { PLATFORMS };
