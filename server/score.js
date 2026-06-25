// Calcolo del punteggio di esposizione (0–100, più alto = più esposto).
// Logica condivisa così backend e report sono coerenti col frontend.

export function emailScore(breaches) {
  const found = breaches.filter((b) => b).length;
  return Math.min(100, found * 22 + (found ? 8 : 0));
}

export function usernameScore(platforms) {
  const exposed = platforms.filter((p) => p.status === "exposed").length;
  return Math.min(100, exposed * 15 + (exposed ? 5 : 0));
}

export function scoreMeta(score) {
  if (score >= 66)
    return {
      level: "high",
      label: "Esposizione alta",
      desc: "I tuoi dati compaiono in più fonti pubbliche. Cambia le password riutilizzate e attiva la 2FA.",
    };
  if (score >= 33)
    return {
      level: "medium",
      label: "Esposizione media",
      desc: "Qualche traccia pubblica rilevata. Tieni d'occhio gli account riutilizzati.",
    };
  return {
    level: "low",
    label: "Esposizione bassa",
    desc: "Poche tracce pubbliche trovate. Buona igiene digitale, continua così.",
  };
}
