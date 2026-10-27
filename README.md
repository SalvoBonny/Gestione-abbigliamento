# Gestione abbigliamento



App web per gestire il magazzino di abbigliamento (maglie, felpe, giubbotti) e raccogliere le richieste delle persone, con taglie e quantità.



## Cosa fa



- **Modulo pubblico:** chi ha bisogno di abbigliamento inserisce nome e cognome e sceglie articolo, taglia e quantità. Prima di inviare deve spuntare la casella dell'informativa privacy.

- **Area amministratore** (protetta da password):

&#x20;   - aggiunge o toglie pezzi dal magazzino

&#x20;   - vede il totale richiesto per taglia e quanto resta da ordinare

&#x20;   - segna le richieste come consegnate, scalando la giacenza

&#x20;   - cancella le richieste consegnate (nomi compresi)



## Privacy



I dati personali (nome e cognome) restano nel database locale `magazzino.db`, che **non è nel repository** (è escluso con `.gitignore`). La password e i contatti per l'informativa si leggono dal file `.env`, anch'esso escluso.



## Tecnologie



- Python

- Streamlit: pagina web

- SQLite: database

- pandas: tabelle e totali



## Installazione su Windows



1. Installa Python da python.org (spunta "Add python.exe to PATH").

2. In PowerShell, nella cartella del progetto:



```

python -m pip install -r requirements.txt

copy .env.example .env

```



3. Apri `.env` e scrivi la tua password amministratore, il nome di chi gestisce i dati e un'email di contatto.



## Avvio



```

python -m streamlit run app.py

```



Si apre il browser su http://localhost:8501. Il database viene creato al primo avvio.



## Note



Progetto sviluppato da Salvo con l'aiuto di strumenti di intelligenza artificiale (Claude e Cursor).

