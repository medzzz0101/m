// ---------------------------------------------------------------------------
// Have I Been Pwned client (server-side only).
// La chiave API non lascia mai il backend. Se manca, restituiamo dati demo.
// Docs: https://haveibeenpwned.com/API/v3
// ---------------------------------------------------------------------------

const HIBP_BASE = "https://haveibeenpwned.com/api/v3";

const DEMO_BREACHES = [
  { name: "Collection #1", title: "Collection #1", year: 2019, dataClasses: ["Email addresses", "Passwords"], demo: true },
  { name: "LinkedIn", title: "LinkedIn", year: 2021, dataClasses: ["Email addresses", "Phone numbers", "Geographic locations"], demo: true },
  { name: "Dropbox", title: "Dropbox", year: 2016, dataClasses: ["Email addresses", "Passwords"], demo: true },
  { name: "Adobe", title: "Adobe", year: 2013, dataClasses: ["Email addresses", "Password hints", "Passwords"], demo: true },
];

function yearFromBreach(b) {
  if (b.BreachDate) return Number(b.BreachDate.slice(0, 4));
  if (b.AddedDate) return Number(b.AddedDate.slice(0, 4));
  return null;
}

/**
 * Cerca i breach in cui compare un'email.
 * @returns {Promise<{demo:boolean, breaches:Array, error?:string}>}
 */
export async function checkEmailBreaches(email, { apiKey, userAgent }) {
  // Senza chiave: modalità demo (utile per girare la UI senza pagare HIBP).
  if (!apiKey) {
    return { demo: true, breaches: DEMO_BREACHES };
  }

  const url =
    `${HIBP_BASE}/breachedaccount/${encodeURIComponent(email)}` +
    `?truncateResponse=false`;

  let res;
  try {
    res = await fetch(url, {
      headers: {
        "hibp-api-key": apiKey,
        "user-agent": userAgent || "FootprintChecker-SelfCheck",
        accept: "application/json",
      },
    });
  } catch (err) {
    return { demo: false, breaches: [], error: "Impossibile contattare HIBP: " + err.message };
  }

  // 404 = nessun breach trovato (account "pulito").
  if (res.status === 404) return { demo: false, breaches: [] };

  if (res.status === 401) return { demo: false, breaches: [], error: "Chiave HIBP non valida." };
  if (res.status === 429) {
    const retry = res.headers.get("retry-after");
    return { demo: false, breaches: [], error: `Rate limit HIBP. Riprova tra ${retry || "qualche"} secondi.` };
  }
  if (!res.ok) return { demo: false, breaches: [], error: `HIBP ha risposto ${res.status}.` };

  let data;
  try {
    data = await res.json();
  } catch {
    return { demo: false, breaches: [], error: "Risposta HIBP non valida." };
  }

  const breaches = (Array.isArray(data) ? data : []).map((b) => ({
    name: b.Name,
    title: b.Title || b.Name,
    year: yearFromBreach(b),
    dataClasses: b.DataClasses || [],
    demo: false,
  }));

  return { demo: false, breaches };
}
