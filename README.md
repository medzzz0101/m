# 🛡️ Footprint Checker

Web app di **self-check OSINT**: inserisci la **tua** email o username e ottieni
un report di esposizione pubblica — in quali data breach noti compare l'email e
su quali piattaforme pubbliche esiste lo username.

> ⚠️ **Vincolo non negoziabile.** Lo strumento serve solo a controllare la
> **propria** esposizione o quella di chi dà il **consenso esplicito**. Niente
> ricerca di terzi a loro insaputa, niente scraping/ricerca di massa su persone
> non consenzienti. Il consenso è obbligatorio sia nella UI sia lato backend.

---

## Stato del progetto

| Fase | Stato |
|------|-------|
| **1. Frontend statico** (input + risultati animati) | ✅ fatto |
| **2. Backend proxy** (Node/Express, niente chiavi nel frontend) | ✅ fatto |
| **3. Integrazione Have I Been Pwned** (email) | ✅ fatto (demo se manca la chiave) |
| **4. Check username stile Sherlock** (piattaforme pubbliche) | ✅ fatto |
| **5. Monetizzazione** (free vs premium, report scaricabile) | ✅ fatto (stub pagamento) |
| 6. Pagamenti reali, account, monitoraggio continuo | ⏳ prossimo |

## Avvio rapido

```bash
npm install
cp .env.example .env       # opzionale: aggiungi la chiave HIBP
npm start                  # http://localhost:3000
```

Senza chiave HIBP il check email gira in **modalità demo** (breach fittizi),
così puoi provare tutto il flusso senza pagare l'API. Il check username
funziona comunque davvero (interroga le piattaforme pubbliche).

> Vuoi solo la demo visiva, senza server? Apri direttamente `index.html`: il
> frontend rileva l'assenza del backend e ricade automaticamente sui dati mock.

## Architettura

```
[ Frontend React ]  ──►  [ Backend Express ]  ──►  [ HIBP API ]        (email)
   index.html            server/index.js       └─►  [ piattaforme pubbliche ]  (username)
   input + UI animata    tiene la API key
   nessun segreto        consenso + quota
```

Il frontend non conosce **mai** la chiave HIBP: ogni chiamata passa dal backend.

### Endpoint

| Metodo | Path | Descrizione |
|--------|------|-------------|
| `POST` | `/api/scan/email` | `{ email, consent }` → breach noti + punteggio |
| `POST` | `/api/scan/username` | `{ username, consent }` → presenza su piattaforme + punteggio |
| `POST` | `/api/report` | Premium (`x-premium: 1`) → report HTML scaricabile (stampabile in PDF) |
| `GET`  | `/api/health` | stato server, configurazione HIBP, quota |

- **Consenso**: senza `consent: true` il backend risponde `403`.
- **Quota free**: `FREE_SCANS` (default 2) per visitatore, in-memory (niente DB).
  Esaurita → `402`. Premium (`x-premium: 1`) bypassa la quota.
- **Punteggio di esposizione** 0–100 calcolato lato server (`server/score.js`).

### Struttura

```
index.html              frontend (React via CDN, zero build)
server/
  index.js              Express: routing, consenso, quota, static
  hibp.js               client Have I Been Pwned (demo se manca la chiave)
  usernameCheck.js      check presenza username (stile Sherlock, concorrenza limitata)
  score.js              punteggio di esposizione + livelli
  report.js             generatore report HTML (Premium)
.env.example            config (HIBP_API_KEY, PORT, FREE_SCANS)
```

## Funzionalità

- Tab **Email** / **Username** con scansione animata e **reveal progressivo** dei risultati
- **Punteggio di esposizione** con gauge circolare (basso / medio / alto)
- **Email** → lista data breach noti (HIBP); **username** → presenza pubblica su
  GitHub, Reddit, Instagram, TikTok, GitLab, Steam, Telegram, Twitch
- **Free**: 2 scansioni · **Premium**: scansioni illimitate + report scaricabile
- **Consenso obbligatorio** + banner etico

## Note sui check username

I check stile Sherlock leggono solo lo **status della pagina profilo pubblica**
(esiste / non esiste). Alcune piattaforme con login wall o anti-bot possono
restituire esito **INCERTO**: è una limitazione nota dell'approccio, non un bug.

## Etica & ambito

Strumento **difensivo**. Pensato per ridurre la propria superficie di esposizione:
sapere dove cambiare password, attivare la 2FA, rimuovere account pubblici inutili.
**Non** è uno strumento di profilazione di terzi.
