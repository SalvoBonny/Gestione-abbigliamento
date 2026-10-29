"""Gestione magazzino: abbigliamento (con richieste dal modulo pubblico)
e alimenti (con scadenze e scansione dei codici a barre).

I dati stanno in un database Postgres online (Neon). Password e stringa di
connessione si leggono dal file .env (sul PC) o dai "Secrets" (online).
"""

import hmac
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import streamlit as st
from dotenv import load_dotenv

# Deve essere il primo comando di Streamlit
st.set_page_config(page_title="Gestione magazzino", page_icon="📦")

# Legge il file .env (sul tuo PC). Online non esiste e si usano i Secrets.
load_dotenv()


def leggi_config(nome, default=None):
    """Legge un valore da .env / variabili d'ambiente, poi dai Secrets di Streamlit."""
    valore = os.getenv(nome)
    if valore:
        return valore
    try:
        return st.secrets.get(nome, default)
    except Exception:
        return default


# ---------- Impostazioni ----------
# Nessuna password di riserva: se manca, l'area amministratore resta disattivata
PASSWORD = leggi_config("ADMIN_PASSWORD")
DATABASE_URL = leggi_config("DATABASE_URL")
TITOLARE = leggi_config("TITOLARE_DATI", "[nome di chi gestisce la raccolta]")
CONTATTO_PRIVACY = leggi_config("CONTATTO_PRIVACY", "[email di contatto]")

FUSO = ZoneInfo("Europe/Rome")

ARTICOLI = ["Maglia", "Felpa", "Giubbotto"]
TAGLIE = ["XS", "S", "M", "L", "XL", "XXL"]

CATEGORIE_ALIMENTI = [
    "Pasta e riso",
    "Conserve e legumi",
    "Latticini e uova",
    "Prodotti da forno",
    "Bevande",
    "Dolci e snack",
    "Altro",
]
UNITA = ["pezzi", "confezioni", "scatole", "bottiglie"]

# Quanti giorni prima della scadenza mostrare l'avviso
GIORNI_AVVISO = 30


def oggi():
    """Data di oggi in Italia."""
    return datetime.now(FUSO).date()


# ---------- Database ----------
def connetti():
    """Apre la connessione. Se il database era sospeso, riprova qualche volta."""
    ultimo_errore = None
    for _ in range(3):
        try:
            return psycopg.connect(DATABASE_URL, connect_timeout=15)
        except psycopg.OperationalError as errore:
            ultimo_errore = errore
            time.sleep(2)
    raise ultimo_errore


@st.cache_resource
def inizializza_db():
    """Crea le tabelle se non esistono (si fa una volta sola)."""
    istruzioni = [
        """CREATE TABLE IF NOT EXISTS magazzino (
            articolo TEXT,
            taglia TEXT,
            quantita INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (articolo, taglia)
        )""",
        """CREATE TABLE IF NOT EXISTS richieste (
            id SERIAL PRIMARY KEY,
            data TIMESTAMPTZ NOT NULL DEFAULT now(),
            nome TEXT NOT NULL,
            articolo TEXT NOT NULL,
            taglia TEXT NOT NULL,
            quantita INTEGER NOT NULL,
            stato TEXT NOT NULL DEFAULT 'in attesa'
        )""",
        """CREATE TABLE IF NOT EXISTS prodotti (
            id SERIAL PRIMARY KEY,
            codice TEXT UNIQUE,
            nome TEXT NOT NULL,
            categoria TEXT NOT NULL,
            unita TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS lotti (
            id SERIAL PRIMARY KEY,
            prodotto_id INTEGER NOT NULL REFERENCES prodotti(id) ON DELETE CASCADE,
            quantita INTEGER NOT NULL CHECK (quantita >= 0),
            scadenza DATE
        )""",
        "ALTER TABLE lotti ADD COLUMN IF NOT EXISTS codice_lotto TEXT",
        """CREATE TABLE IF NOT EXISTS movimenti (
            id SERIAL PRIMARY KEY,
            data TIMESTAMPTZ NOT NULL DEFAULT now(),
            prodotto_id INTEGER REFERENCES prodotti(id) ON DELETE SET NULL,
            lotto_id INTEGER,
            delta INTEGER NOT NULL,
            tipo TEXT NOT NULL
        )""",
    ]
    with connetti() as con:
        for istruzione in istruzioni:
            con.execute(istruzione)
    return True


# ---------- Abbigliamento: dati ----------
def leggi_magazzino():
    with connetti() as con:
        righe = con.execute(
            "SELECT articolo, taglia, quantita FROM magazzino"
        ).fetchall()
    return pd.DataFrame(righe, columns=["articolo", "taglia", "quantita"])


def modifica(articolo, taglia, delta):
    """Aggiunge o toglie pezzi (la giacenza non scende mai sotto zero)."""
    with connetti() as con:
        con.execute(
            "INSERT INTO magazzino (articolo, taglia, quantita) "
            "VALUES (%s, %s, GREATEST(0, %s)) "
            "ON CONFLICT (articolo, taglia) DO UPDATE "
            "SET quantita = GREATEST(0, magazzino.quantita + %s)",
            (articolo, taglia, delta, delta),
        )


def salva_richiesta(nome, righe):
    with connetti() as con:
        for articolo, taglia, quantita in righe:
            con.execute(
                "INSERT INTO richieste (nome, articolo, taglia, quantita) "
                "VALUES (%s, %s, %s, %s)",
                (nome, articolo, taglia, quantita),
            )


def leggi_richieste():
    with connetti() as con:
        righe = con.execute(
            "SELECT id, data, nome, articolo, taglia, quantita, stato "
            "FROM richieste ORDER BY id DESC"
        ).fetchall()
    df = pd.DataFrame(
        righe,
        columns=["id", "data", "nome", "articolo", "taglia", "quantita", "stato"],
    )
    if not df.empty:
        df["data"] = df["data"].apply(
            lambda d: d.astimezone(FUSO).strftime("%d/%m/%Y %H:%M")
        )
    return df


def consegna(id_richiesta):
    """Segna la richiesta come consegnata e scala la giacenza."""
    with connetti() as con:
        r = con.execute(
            "SELECT articolo, taglia, quantita FROM richieste "
            "WHERE id = %s AND stato = 'in attesa' FOR UPDATE",
            (id_richiesta,),
        ).fetchone()
        if r is None:
            return "Richiesta non trovata o già consegnata."
        articolo, taglia, quantita = r
        riga = con.execute(
            "SELECT quantita FROM magazzino "
            "WHERE articolo = %s AND taglia = %s FOR UPDATE",
            (articolo, taglia),
        ).fetchone()
        disponibili = riga[0] if riga else 0
        if disponibili < quantita:
            return (
                f"Giacenza insufficiente: {articolo} {taglia}, "
                f"ne hai {disponibili} e ne servono {quantita}."
            )
        con.execute(
            "UPDATE magazzino SET quantita = quantita - %s "
            "WHERE articolo = %s AND taglia = %s",
            (quantita, articolo, taglia),
        )
        con.execute(
            "UPDATE richieste SET stato = 'consegnata' WHERE id = %s",
            (id_richiesta,),
        )
    return None


def elimina_consegnate():
    """Cancella le richieste già consegnate (nomi compresi). Restituisce quante."""
    with connetti() as con:
        cur = con.execute("DELETE FROM richieste WHERE stato = 'consegnata'")
        return cur.rowcount


def tabella(df, colonna):
    """Tabella articolo x taglia con la somma della colonna indicata."""
    if df.empty:
        return pd.DataFrame(0, index=ARTICOLI, columns=TAGLIE)
    return (
        df.pivot_table(
            index="articolo", columns="taglia", values=colonna, aggfunc="sum"
        )
        .reindex(index=ARTICOLI, columns=TAGLIE)
        .fillna(0)
        .astype(int)
    )


def con_totali(df):
    """Aggiunge la colonna e la riga Totale."""
    df = df.copy()
    df["Totale"] = df.sum(axis=1)
    df.loc["Totale"] = df.sum()
    return df


# ---------- Alimenti: dati ----------
def trova_prodotto(codice):
    """Cerca un prodotto dal codice a barre. Restituisce (id, nome, categoria, unita) o None."""
    with connetti() as con:
        return con.execute(
            "SELECT id, nome, categoria, unita FROM prodotti WHERE codice = %s",
            (codice,),
        ).fetchone()


def trova_prodotto_per_id(prodotto_id):
    """Cerca un prodotto dal suo numero. Restituisce (id, nome, categoria, unita) o None."""
    with connetti() as con:
        return con.execute(
            "SELECT id, nome, categoria, unita FROM prodotti WHERE id = %s",
            (prodotto_id,),
        ).fetchone()


def crea_prodotto(codice, nome, categoria, unita):
    """Registra un prodotto nuovo. Restituisce l'id, oppure None se il codice esiste già."""
    codice = codice.strip() or None
    with connetti() as con:
        if codice is not None:
            esiste = con.execute(
                "SELECT id FROM prodotti WHERE codice = %s", (codice,)
            ).fetchone()
            if esiste:
                return None
        return con.execute(
            "INSERT INTO prodotti (codice, nome, categoria, unita) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (codice, nome, categoria, unita),
        ).fetchone()[0]


def elenco_prodotti():
    with connetti() as con:
        return con.execute(
            "SELECT id, nome, categoria, unita, codice FROM prodotti "
            "ORDER BY categoria, nome"
        ).fetchall()


def carica(prodotto_id, quantita, scadenza, codice_lotto=None):
    """Aggiunge pezzi. Se esiste già un lotto con stessa scadenza e stesso codice, li somma."""
    codice_lotto = (codice_lotto or "").strip() or None
    with connetti() as con:
        riga = con.execute(
            "SELECT id FROM lotti WHERE prodotto_id = %s "
            "AND scadenza IS NOT DISTINCT FROM %s::date "
            "AND codice_lotto IS NOT DISTINCT FROM %s::text",
            (prodotto_id, scadenza, codice_lotto),
        ).fetchone()
        if riga:
            lotto_id = riga[0]
            con.execute(
                "UPDATE lotti SET quantita = quantita + %s WHERE id = %s",
                (quantita, lotto_id),
            )
        else:
            lotto_id = con.execute(
                "INSERT INTO lotti (prodotto_id, quantita, scadenza, codice_lotto) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (prodotto_id, quantita, scadenza, codice_lotto),
            ).fetchone()[0]
        con.execute(
            "INSERT INTO movimenti (prodotto_id, lotto_id, delta, tipo) "
            "VALUES (%s, %s, %s, 'carico')",
            (prodotto_id, lotto_id, quantita),
        )


def scarica(prodotto_id, quantita):
    """Toglie pezzi partendo dal lotto con la scadenza più vicina."""
    with connetti() as con:
        lotti = con.execute(
            "SELECT id, quantita FROM lotti WHERE prodotto_id = %s AND quantita > 0 "
            "ORDER BY scadenza ASC NULLS LAST, id FOR UPDATE",
            (prodotto_id,),
        ).fetchall()
        totale = sum(q for _, q in lotti)
        if totale < quantita:
            return f"Giacenza insufficiente: ne hai {totale}."
        restante = quantita
        for lotto_id, disponibili in lotti:
            if restante <= 0:
                break
            prendi = min(disponibili, restante)
            con.execute(
                "UPDATE lotti SET quantita = quantita - %s WHERE id = %s",
                (prendi, lotto_id),
            )
            con.execute(
                "INSERT INTO movimenti (prodotto_id, lotto_id, delta, tipo) "
                "VALUES (%s, %s, %s, 'scarico')",
                (prodotto_id, lotto_id, -prendi),
            )
            restante -= prendi
    return None


def totale_prodotto(prodotto_id):
    with connetti() as con:
        return con.execute(
            "SELECT COALESCE(SUM(quantita), 0) FROM lotti WHERE prodotto_id = %s",
            (prodotto_id,),
        ).fetchone()[0]


def leggi_lotti():
    with connetti() as con:
        righe = con.execute(
            "SELECT l.id, p.nome, p.categoria, l.quantita, p.unita, l.scadenza, "
            "l.codice_lotto, p.codice "
            "FROM lotti l JOIN prodotti p ON p.id = l.prodotto_id "
            "WHERE l.quantita > 0 "
            "ORDER BY l.scadenza ASC NULLS LAST, p.nome"
        ).fetchall()
    return pd.DataFrame(
        righe,
        columns=[
            "id", "prodotto", "categoria", "quantita", "unita", "scadenza",
            "codice_lotto", "codice_barre",
        ],
    )


def leggi_totali_prodotti():
    with connetti() as con:
        righe = con.execute(
            "SELECT p.codice, p.nome, p.categoria, COALESCE(SUM(l.quantita), 0), p.unita "
            "FROM prodotti p LEFT JOIN lotti l ON l.prodotto_id = p.id "
            "GROUP BY p.id ORDER BY p.categoria, p.nome"
        ).fetchall()
    df = pd.DataFrame(
        righe,
        columns=["codice a barre", "prodotto", "categoria", "totale", "unita"],
    )
    df["codice a barre"] = df["codice a barre"].apply(
        lambda c: c if isinstance(c, str) and c else "—"
    )
    return df


def correggi_lotto(lotto_id, nuova_quantita):
    """Imposta la quantità di un lotto (per correggere errori) e lo registra."""
    with connetti() as con:
        riga = con.execute(
            "SELECT prodotto_id, quantita FROM lotti WHERE id = %s FOR UPDATE",
            (lotto_id,),
        ).fetchone()
        if riga is None:
            return
        prodotto_id, vecchia = riga
        con.execute(
            "UPDATE lotti SET quantita = %s WHERE id = %s", (nuova_quantita, lotto_id)
        )
        con.execute(
            "INSERT INTO movimenti (prodotto_id, lotto_id, delta, tipo) "
            "VALUES (%s, %s, %s, 'correzione')",
            (prodotto_id, lotto_id, nuova_quantita - vecchia),
        )


def elimina_lotto(lotto_id):
    with connetti() as con:
        riga = con.execute(
            "SELECT prodotto_id, quantita FROM lotti WHERE id = %s FOR UPDATE",
            (lotto_id,),
        ).fetchone()
        if riga is None:
            return
        prodotto_id, quantita = riga
        con.execute("DELETE FROM lotti WHERE id = %s", (lotto_id,))
        con.execute(
            "INSERT INTO movimenti (prodotto_id, lotto_id, delta, tipo) "
            "VALUES (%s, %s, %s, 'eliminazione')",
            (prodotto_id, lotto_id, -quantita),
        )


def leggi_movimenti(quanti=20):
    with connetti() as con:
        righe = con.execute(
            "SELECT m.data, COALESCE(p.nome, '(prodotto eliminato)'), m.delta, m.tipo "
            "FROM movimenti m LEFT JOIN prodotti p ON p.id = m.prodotto_id "
            "ORDER BY m.id DESC LIMIT %s",
            (quanti,),
        ).fetchall()
    df = pd.DataFrame(righe, columns=["data", "prodotto", "variazione", "tipo"])
    if not df.empty:
        df["data"] = df["data"].apply(
            lambda d: d.astimezone(FUSO).strftime("%d/%m/%Y %H:%M")
        )
    return df


def prepara_lotti(df):
    """Aggiunge i giorni alla scadenza e scrive la data in formato italiano."""
    vista = df.copy()
    giorni = [(s - oggi()).days if s is not None else pd.NA for s in vista["scadenza"]]
    vista["giorni"] = pd.Series(giorni, index=vista.index, dtype="Int64")
    vista["scadenza"] = vista["scadenza"].apply(
        lambda s: s.strftime("%d/%m/%Y") if s is not None else "—"
    )
    for colonna in ["codice_lotto", "codice_barre"]:
        vista[colonna] = vista[colonna].apply(
            lambda c: c if isinstance(c, str) and c else "—"
        )
    return vista


# ---------- Privacy ----------
def testo_informativa():
    """Testo dell'informativa privacy mostrato nel modulo."""
    return (
        f"**Chi tratta i dati:** {TITOLARE}. Contatto: {CONTATTO_PRIVACY}.\n\n"
        "**Quali dati:** raccogliamo solo il tuo nome e cognome, insieme alla "
        "richiesta (tipo di capo, taglia e quantità).\n\n"
        "**Perché:** per organizzare la distribuzione dell'abbigliamento e "
        "sapere a chi consegnarlo.\n\n"
        "**Dove sono salvati:** su un database online (servizio Neon) con "
        "server in Europa (Francoforte).\n\n"
        "**Chi li vede:** solo chi gestisce la distribuzione. I dati non vengono "
        "pubblicati né ceduti a terzi.\n\n"
        "**Per quanto tempo:** fino al termine della distribuzione, poi vengono "
        "cancellati.\n\n"
        "**I tuoi diritti:** puoi chiedere di vedere, correggere o cancellare i "
        f"tuoi dati scrivendo a {CONTATTO_PRIVACY}."
    )


# ---------- Pagina pubblica ----------
def pagina_pubblica():
    st.title("👕 Richiesta abbigliamento")
    st.write(
        "Compila il modulo: per ogni articolo scegli la taglia e la quantità "
        "(lascia 0 se non ti serve)."
    )
    with st.form("richiesta"):
        nome = st.text_input("Nome e cognome")
        righe = []
        for art in ARTICOLI:
            st.markdown(f"**{art}**")
            c1, c2 = st.columns(2)
            taglia = c1.selectbox("Taglia", TAGLIE, index=2, key=f"t_{art}")
            qta = c2.number_input(
                "Quantità", min_value=0, max_value=20, value=0, step=1, key=f"q_{art}"
            )
            righe.append((art, taglia, int(qta)))

        with st.expander("Informativa sulla privacy"):
            st.markdown(testo_informativa())
        accetto = st.checkbox("Ho letto l'informativa sulla privacy")

        if st.form_submit_button("Invia richiesta"):
            richieste = [r for r in righe if r[2] > 0]
            if not nome.strip():
                st.error("Inserisci nome e cognome.")
            elif not richieste:
                st.error("Scegli almeno un articolo.")
            elif not accetto:
                st.error("Per inviare devi spuntare la casella sull'informativa.")
            else:
                try:
                    salva_richiesta(nome.strip(), richieste)
                    st.success("Richiesta inviata, grazie!")
                except Exception:
                    st.error("Non sono riuscito a salvare la richiesta. Riprova tra poco.")


# ---------- Area amministratore: abbigliamento ----------
def scheda_abbigliamento():
    st.subheader("Aggiungi o togli pezzi")
    with st.form("modifica"):
        articolo = st.selectbox("Articolo", ARTICOLI)
        taglia = st.selectbox("Taglia", TAGLIE)
        delta = st.number_input("Quantità (negativa per togliere)", value=0, step=1)
        if st.form_submit_button("Aggiorna"):
            modifica(articolo, taglia, int(delta))
            st.success(f"{articolo} {taglia}: aggiornato di {int(delta):+d}")

    st.subheader("Giacenze attuali")
    df = leggi_magazzino()
    if df.empty:
        st.info("Il magazzino è vuoto. Aggiungi i primi pezzi qui sopra.")
    else:
        giacenze_tab = (
            df.pivot(index="articolo", columns="taglia", values="quantita")
            .reindex(index=ARTICOLI, columns=TAGLIE)
            .fillna(0)
            .astype(int)
        )
        st.dataframe(giacenze_tab)


def scheda_richieste():
    rich = leggi_richieste()
    if rich.empty:
        st.info("Nessuna richiesta ricevuta.")
        return

    in_attesa = rich[rich["stato"] == "in attesa"]
    richiesti = tabella(in_attesa, "quantita")
    giacenze = tabella(leggi_magazzino(), "quantita")
    da_ordinare = (richiesti - giacenze).clip(lower=0)

    st.subheader("Totale richiesto per taglia")
    st.caption("Solo richieste in attesa di consegna")
    st.dataframe(con_totali(richiesti))

    st.subheader("Da ordinare")
    st.caption("Richiesto meno quanto hai già in magazzino")
    st.dataframe(con_totali(da_ordinare))

    st.subheader("Elenco richieste")
    st.dataframe(rich, hide_index=True)
    if not in_attesa.empty:
        id_sel = st.selectbox("Segna come consegnata (ID richiesta)", in_attesa["id"])
        if st.button("Consegnata"):
            errore = consegna(int(id_sel))
            if errore:
                st.error(errore)
            else:
                st.rerun()

    # Privacy: cancellazione dei dati personali non più necessari
    consegnate = rich[rich["stato"] == "consegnata"]
    if not consegnate.empty:
        st.subheader("Privacy: cancella i dati")
        conferma = st.checkbox(
            f"Confermo: cancellare le righe già consegnate ({len(consegnate)}), "
            "nomi compresi"
        )
        if st.button("Cancella richieste consegnate"):
            if conferma:
                elimina_consegnate()
                st.rerun()
            else:
                st.warning("Spunta prima la casella di conferma.")


# ---------- Area amministratore: alimenti ----------
def scheda_scansione():
    st.caption(
        "Con la pistola: clicca nella casella e leggi il codice, lei preme Invio da sola. "
        "Senza pistola puoi scrivere il codice a mano o scegliere il prodotto dalla lista. "
        "Dopo ogni lettura potresti dover cliccare di nuovo nella casella."
    )
    modo = st.radio(
        "Operazione", ["Scarico (togli)", "Carico (aggiungi)"], horizontal=True
    )
    scarico = modo.startswith("Scarico")

    prodotti = elenco_prodotti()
    scelte = {p[0]: f"{p[1]} ({p[3]})" for p in prodotti}

    with st.form("scansione", clear_on_submit=True):
        codice = st.text_input("Codice a barre")
        scelto = st.selectbox(
            "Oppure scegli il prodotto dalla lista",
            [None] + list(scelte.keys()),
            format_func=lambda i: "—" if i is None else scelte[i],
        )
        quantita = st.number_input("Quantità", min_value=1, value=1, step=1)
        scadenza = None
        codice_lotto = ""
        if not scarico:
            scadenza = st.date_input(
                "Scadenza (se c'è)", value=None, format="DD/MM/YYYY"
            )
            codice_lotto = st.text_input(
                "Codice lotto (stampato sulla confezione, facoltativo)"
            )
        invio = st.form_submit_button("Conferma")

    if invio:
        codice = codice.strip()
        if codice:
            prodotto = trova_prodotto(codice)
        elif scelto is not None:
            prodotto = trova_prodotto_per_id(scelto)
        else:
            prodotto = None
        if not codice and scelto is None:
            st.error("Scrivi il codice a barre oppure scegli un prodotto dalla lista.")
        elif scarico:
            if prodotto is None:
                st.error(
                    "Codice non registrato. Passa a Carico per registrare il prodotto."
                )
            else:
                errore = scarica(prodotto[0], int(quantita))
                if errore:
                    st.error(f"{prodotto[1]}: {errore}")
                else:
                    rimasti = totale_prodotto(prodotto[0])
                    st.success(
                        f"{prodotto[1]}: tolti {int(quantita)}. "
                        f"Ora ne restano {rimasti} {prodotto[3]}."
                    )
        else:
            if prodotto is None:
                # Prodotto nuovo: chiede i dati e ricorda cosa caricare
                st.session_state.nuovo_prodotto = {
                    "codice": codice,
                    "quantita": int(quantita),
                    "scadenza": scadenza,
                    "codice_lotto": codice_lotto,
                }
            else:
                carica(prodotto[0], int(quantita), scadenza, codice_lotto)
                totale = totale_prodotto(prodotto[0])
                st.success(
                    f"{prodotto[1]}: aggiunti {int(quantita)}. "
                    f"Ora ne hai {totale} {prodotto[3]}."
                )

    # Modulo per registrare un prodotto mai visto
    nuovo = st.session_state.get("nuovo_prodotto")
    if nuovo:
        st.info(f"Codice {nuovo['codice']} non registrato. Inserisci i dati del prodotto.")
        with st.form("nuovo_prodotto"):
            nome = st.text_input("Nome del prodotto")
            categoria = st.selectbox("Categoria", CATEGORIE_ALIMENTI)
            unita = st.selectbox("Unità", UNITA)
            c1, c2 = st.columns(2)
            salva = c1.form_submit_button("Registra e carica")
            annulla = c2.form_submit_button("Annulla")
        if annulla:
            st.session_state.nuovo_prodotto = None
            st.rerun()
        if salva:
            if not nome.strip():
                st.error("Inserisci il nome del prodotto.")
            else:
                prodotto_id = crea_prodotto(nuovo["codice"], nome.strip(), categoria, unita)
                if prodotto_id is None:
                    st.error("Questo codice è già registrato.")
                else:
                    carica(
                        prodotto_id,
                        nuovo["quantita"],
                        nuovo["scadenza"],
                        nuovo["codice_lotto"],
                    )
                    st.session_state.nuovo_prodotto = None
                    st.success(f"{nome.strip()}: registrato e caricati {nuovo['quantita']}.")


def scheda_giacenze():
    lotti = leggi_lotti()
    if lotti.empty:
        st.info("Nessun alimento in magazzino. Registra i primi prodotti.")
    else:
        vista = prepara_lotti(lotti)
        nomi = {
            "codice_lotto": "codice lotto",
            "codice_barre": "codice a barre",
            "id": "n.",
        }
        colonne_avviso = [
            "codice_lotto", "prodotto", "codice_barre",
            "quantita", "unita", "scadenza", "giorni",
        ]

        scaduti = vista[vista["giorni"].notna() & (vista["giorni"] < 0)]
        in_scadenza = vista[
            vista["giorni"].notna()
            & (vista["giorni"] >= 0)
            & (vista["giorni"] <= GIORNI_AVVISO)
        ]
        if not scaduti.empty:
            st.error("Prodotti già scaduti:")
            st.dataframe(
                scaduti[colonne_avviso].rename(columns=nomi), hide_index=True
            )
        if not in_scadenza.empty:
            st.warning(f"Prodotti che scadono entro {GIORNI_AVVISO} giorni:")
            st.dataframe(
                in_scadenza[colonne_avviso].rename(columns=nomi), hide_index=True
            )

        st.subheader("Totale per prodotto")
        st.dataframe(leggi_totali_prodotti(), hide_index=True)

        st.subheader("Lotti (ordinati per scadenza)")
        st.dataframe(
            vista[
                [
                    "id", "codice_lotto", "prodotto", "codice_barre", "categoria",
                    "quantita", "unita", "scadenza", "giorni",
                ]
            ].rename(columns=nomi),
            hide_index=True,
        )

        st.subheader("Correggi o elimina un lotto")
        etichette = {
            int(r.id): (
                f"{r.prodotto} - lotto {r.codice_lotto} "
                f"({r.quantita} {r.unita}, scad. {r.scadenza}) [n. {r.id}]"
            )
            for r in vista.itertuples()
        }
        lotto_id = st.selectbox(
            "Lotto", list(etichette.keys()), format_func=lambda i: etichette[i]
        )
        nuova = st.number_input("Nuova quantità", min_value=0, value=0, step=1)
        c1, c2 = st.columns(2)
        if c1.button("Salva quantità"):
            correggi_lotto(int(lotto_id), int(nuova))
            st.rerun()
        conferma = c2.checkbox("Confermo eliminazione")
        if c2.button("Elimina lotto"):
            if conferma:
                elimina_lotto(int(lotto_id))
                st.rerun()
            else:
                st.warning("Spunta prima la conferma.")

    with st.expander("Ultimi movimenti"):
        movimenti = leggi_movimenti()
        if movimenti.empty:
            st.write("Nessun movimento.")
        else:
            st.dataframe(movimenti, hide_index=True)


def scheda_prodotti():
    st.subheader("Nuovo prodotto")
    with st.form("prodotto", clear_on_submit=True):
        codice = st.text_input("Codice a barre (facoltativo)")
        nome = st.text_input("Nome del prodotto")
        categoria = st.selectbox("Categoria", CATEGORIE_ALIMENTI)
        unita = st.selectbox("Unità", UNITA)
        if st.form_submit_button("Registra prodotto"):
            if not nome.strip():
                st.error("Inserisci il nome del prodotto.")
            elif crea_prodotto(codice, nome.strip(), categoria, unita) is None:
                st.error("Questo codice a barre è già registrato.")
            else:
                st.success(f"{nome.strip()}: registrato.")

    prodotti = elenco_prodotti()
    if not prodotti:
        st.info("Nessun prodotto registrato.")
        return

    st.subheader("Carica un lotto a mano")
    etichette = {p[0]: f"{p[1]} ({p[3]})" for p in prodotti}
    with st.form("lotto", clear_on_submit=True):
        prodotto_id = st.selectbox(
            "Prodotto", list(etichette.keys()), format_func=lambda i: etichette[i]
        )
        quantita = st.number_input("Quantità", min_value=1, value=1, step=1)
        scadenza = st.date_input("Scadenza (se c'è)", value=None, format="DD/MM/YYYY")
        codice_lotto = st.text_input(
            "Codice lotto (stampato sulla confezione, facoltativo)"
        )
        if st.form_submit_button("Carica"):
            carica(int(prodotto_id), int(quantita), scadenza, codice_lotto)
            st.success(f"{etichette[prodotto_id]}: aggiunti {int(quantita)}.")

    st.subheader("Prodotti registrati")
    st.dataframe(
        pd.DataFrame(
            prodotti, columns=["id", "nome", "categoria", "unita", "codice"]
        ),
        hide_index=True,
    )


# ---------- Menu a sinistra dell'area amministratore ----------
def pag_abbigliamento():
    st.title("👕 Abbigliamento")
    scheda_abbigliamento()


def pag_richieste():
    st.title("📋 Richieste")
    scheda_richieste()


def pag_scansione():
    st.title("📷 Scansione")
    scheda_scansione()


def pag_scadenze():
    st.title("⏳ Giacenze e scadenze")
    scheda_giacenze()


def pag_prodotti():
    st.title("🥫 Prodotti e carico")
    scheda_prodotti()


def mostra_area_admin():
    """Mostra il menu a sinistra (Abbigliamento / Alimenti) e la pagina scelta."""
    pagine = {
        "Abbigliamento": [
            st.Page(
                pag_abbigliamento,
                title="Giacenze",
                icon="👕",
                url_path="abbigliamento",
                default=True,
            ),
            st.Page(pag_richieste, title="Richieste", icon="📋", url_path="richieste"),
        ],
        "Alimenti": [
            st.Page(pag_scansione, title="Scansione", icon="📷", url_path="scansione"),
            st.Page(
                pag_scadenze,
                title="Giacenze e scadenze",
                icon="⏳",
                url_path="scadenze",
            ),
            st.Page(
                pag_prodotti, title="Prodotti e carico", icon="🥫", url_path="prodotti"
            ),
        ],
    }
    st.navigation(pagine).run()


def password_corretta(inserita):
    """Confronta la password in modo sicuro."""
    return hmac.compare_digest(inserita.encode("utf-8"), PASSWORD.encode("utf-8"))


# ---------- Avvio ----------
if not DATABASE_URL:
    st.error(
        "Manca la stringa di connessione al database (DATABASE_URL). "
        "Scrivila nel file .env oppure nei Secrets."
    )
    st.stop()

try:
    inizializza_db()
except Exception as errore:
    st.error("Non riesco a collegarmi al database. Riprova tra qualche secondo.")
    st.caption(f"Dettaglio tecnico: {type(errore).__name__}")
    st.stop()

if "admin" not in st.session_state:
    st.session_state.admin = False

with st.sidebar:
    if st.session_state.admin:
        st.write("Sei nell'area amministratore")
        if st.button("Esci"):
            st.session_state.admin = False
            st.rerun()
    else:
        with st.expander("Area amministratore"):
            if not PASSWORD:
                st.warning("Password non impostata: area amministratore disattivata.")
            else:
                pwd = st.text_input("Password", type="password")
                if st.button("Entra"):
                    if password_corretta(pwd):
                        st.session_state.admin = True
                        st.rerun()
                    else:
                        st.error("Password errata")

if st.session_state.admin:
    mostra_area_admin()
else:
    pagina_pubblica()
