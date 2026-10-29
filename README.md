# Gestione magazzino

App web per gestire un magazzino di **abbigliamento** (maglie, felpe, giubbotti) e di **alimenti**, con un modulo pubblico per raccogliere le richieste di abbigliamento.

## Cosa fa

### Modulo pubblico (abbigliamento)
- Chi ha bisogno di abbigliamento inserisce nome e cognome e sceglie articolo, taglia e quantità.
- Prima di inviare deve spuntare la casella dell'informativa privacy.

### Area amministratore (protetta da password)
Dopo l'accesso compare un menu a sinistra con due sezioni.

**Abbigliamento**
- Giacenze: aggiunge o toglie pezzi per articolo e taglia.
- Richieste: totale richiesto per taglia, quanto resta da ordinare, consegna delle richieste (scala la giacenza) e cancellazione delle richieste consegnate, nomi compresi.

**Alimenti**
- Scansione: carico e scarico con la pistola per codici a barre (che si comporta come una tastiera), scrivendo il codice a mano oppure scegliendo il prodotto da una lista. Lo scarico parte dal lotto con la scadenza più vicina.
- Giacenze e scadenze: totale per prodotto, lotti con codice lotto e codice a barre, avvisi per i prodotti scaduti o in scadenza entro 30 giorni, correzione ed eliminazione dei lotti, registro dei movimenti.
- Prodotti e carico: registrazione dei prodotti e carico dei lotti con scadenza e codice lotto.

## Privacy

- Il modulo raccoglie solo nome e cognome, con un'informativa e una casella da spuntare.
- Il magazzino alimenti non contiene dati personali.
- I nomi non sono visibili al pubblico, solo nell'area amministratore.
- Le richieste consegnate si possono cancellare con un pulsante.
- Il database, la password e i contatti dell'informativa **non sono nel repository**: si leggono dal file `.env` (in locale) o dai "Secrets" (online).

## Tecnologie

- Python
- Streamlit: pagine web e menu
- PostgreSQL (database online gratuito su Neon) con psycopg
- pandas: tabelle e totali

## Configurazione

Copia `.env.example` in `.env` e compila i valori:

| Voce | Significato |
|---|---|
| `ADMIN_PASSWORD` | password dell'area amministratore (senza, l'area resta disattivata) |
| `DATABASE_URL` | stringa di connessione al database Postgres |
| `TITOLARE_DATI` | chi gestisce i dati, per l'informativa |
| `CONTATTO_PRIVACY` | e-mail di contatto per l'informativa |

Le tabelle si creano da sole al primo avvio.

## Installazione su Windows

1. Installa Python da python.org (spunta "Add python.exe to PATH").
2. In PowerShell, nella cartella del progetto:

```
python -m pip install -r requirements.txt
copy .env.example .env
```

3. Apri `.env` e compila i valori.

## Avvio

```
python -m streamlit run app.py
```

Si apre il browser su http://localhost:8501.

## Pubblicazione online

L'app si può pubblicare gratis su Streamlit Community Cloud collegando il repository GitHub. Le quattro voci della tabella qui sopra vanno inserite nei "Secrets" della piattaforma, mai nel codice.

## Limiti noti

- Le quantità sono numeri interi (pezzi, confezioni, scatole, bottiglie).
- Con la pistola, dopo ogni lettura può servire cliccare di nuovo nella casella.
- Il piano gratuito del database non ha backup automatici.

## Idee per il futuro

- Lettura dei codici a barre con la fotocamera del telefono
- Pulsante per annullare l'ultimo movimento

## Note

Progetto sviluppato da Salvo con l'aiuto di strumenti di intelligenza artificiale (Claude e Cursor).
