# 🛡️ Footprint Checker

Web app di **self-check OSINT**: inserisci la **tua** email o username e ottieni
un report di esposizione pubblica — in quali data breach noti compare l'email e
su quali piattaforme pubbliche esiste lo username.

> ⚠️ **Vincolo non negoziabile.** Lo strumento serve solo a controllare la
> **propria** esposizione o quella di chi dà il **consenso esplicito**. Niente
> ricerca di terzi a loro insaputa, niente scraping/ricerca di massa su persone
> non consenzienti.

---

## Stato del progetto

| Fase | Stato |
|------|-------|
| **1. Frontend statico** (input + risultati finti animati) | ✅ **fatto** — questa demo |
| 2. Backend proxy (Node/Python) verso API esterne | ⏳ prossimo |
| 3. Integrazione Have I Been Pwned (email) | ⏳ |
| 4. Check username stile Sherlock (piattaforme pubbliche) | ⏳ |
| 5. Monetizzazione (free vs premium, report scaricabile) | ⏳ |

## Demo (fase 1)

Nessun build, nessun `npm install`. La demo è un singolo file `index.html` che
carica React via CDN — pensato per avere **subito una demo visiva** (es. per un
video).

```bash
# basta aprire il file nel browser:
open index.html        # macOS
xdg-open index.html    # Linux

# oppure servirlo (consigliato, evita problemi di CORS dei CDN):
python3 -m http.server 8000
# poi apri http://localhost:8000
```

### Cosa mostra la demo
- Tab **Email** / **Username** con input e bottone *Scansiona*
- Animazione di scansione con step progressivi e barra di avanzamento
- **Reveal animato** dei risultati uno dopo l'altro (effetto "scena")
- **Punteggio di esposizione** 0–100 con gauge circolare
- Lista breach (email) o presenza su piattaforme (username)
- Limite **2 scansioni gratuite** + upsell **Premium**
- Checkbox di **consenso** obbligatoria prima di ogni scansione

> I dati mostrati nella demo sono **fittizi** (vedi `MOCK_BREACHES` /
> `MOCK_PLATFORMS` in `index.html`). Servono solo a far vedere il flusso visivo.

## Architettura prevista (fase 2+)

```
[ Frontend React ]  ──►  [ Backend proxy ]  ──►  [ HIBP API ]   (email)
   input + UI            (Node o Python)    └─►  [ check username ]  (piattaforme pubbliche)
                          tiene la API key
                          NIENTE chiavi nel frontend
```

- La **chiave API di HIBP** (a pagamento) vive **solo** lato backend.
- Nessun database all'inizio.
- Free: 1–2 scansioni · Premium: scansioni illimitate + report scaricabile.

## Etica & ambito

Strumento difensivo. Pensato per: ridurre la propria superficie di esposizione,
sapere dove cambiare password, attivare la 2FA. **Non** è uno strumento di
profilazione di terzi.
