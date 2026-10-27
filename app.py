import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Legge il file .env (password e contatti): non va mai su GitHub
load_dotenv()

DB = "magazzino.db"
ARTICOLI = ["Maglia", "Felpa", "Giubbotto"]
TAGLIE = ["XS", "S", "M", "L", "XL", "XXL"]

# Nessuna password di riserva: se manca nel .env, l'area amministratore è disattivata
PASSWORD = os.getenv("ADMIN_PASSWORD")

# Dati per l'informativa privacy (si scrivono nel .env, non qui)
TITOLARE = os.getenv("TITOLARE_DATI", "[nome di chi gestisce la raccolta]")
CONTATTO_PRIVACY = os.getenv("CONTATTO_PRIVACY", "[email di contatto]")

# Metti True solo se ti serve davvero un telefono o un'e-mail
CHIEDI_CONTATTO = False


def db():
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS magazzino (
            articolo TEXT,
            taglia TEXT,
            quantita INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (articolo, taglia)
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS richieste (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            nome TEXT,
            contatto TEXT,
            articolo TEXT,
            taglia TEXT,
            quantita INTEGER,
            stato TEXT NOT NULL DEFAULT 'in attesa'
        )"""
    )
    return con


def leggi_magazzino():
    with db() as con:
        return pd.read_sql("SELECT articolo, taglia, quantita FROM magazzino", con)


def modifica(articolo, taglia, delta):
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO magazzino VALUES (?, ?, 0)", (articolo, taglia)
        )
        con.execute(
            "UPDATE magazzino SET quantita = MAX(0, quantita + ?) "
            "WHERE articolo = ? AND taglia = ?",
            (delta, articolo, taglia),
        )


def salva_richiesta(nome, contatto, righe):
    adesso = datetime.now().strftime("%d/%m/%Y %H:%M")
    with db() as con:
        for articolo, taglia, quantita in righe:
            con.execute(
                "INSERT INTO richieste (data, nome, contatto, articolo, taglia, quantita) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (adesso, nome, contatto, articolo, taglia, quantita),
            )


def leggi_richieste():
    with db() as con:
        return pd.read_sql(
            "SELECT id, data, nome, contatto, articolo, taglia, quantita, stato "
            "FROM richieste ORDER BY id DESC",
            con,
        )


def consegna(id_richiesta):
    with db() as con:
        r = con.execute(
            "SELECT articolo, taglia, quantita FROM richieste "
            "WHERE id = ? AND stato = 'in attesa'",
            (id_richiesta,),
        ).fetchone()
        if r is None:
            return "Richiesta non trovata o già consegnata."
        articolo, taglia, quantita = r
        riga = con.execute(
            "SELECT quantita FROM magazzino WHERE articolo = ? AND taglia = ?",
            (articolo, taglia),
        ).fetchone()
        disponibili = riga[0] if riga else 0
        if disponibili < quantita:
            return (
                f"Giacenza insufficiente: {articolo} {taglia}, "
                f"ne hai {disponibili} e ne servono {quantita}."
            )
        con.execute(
            "UPDATE magazzino SET quantita = quantita - ? "
            "WHERE articolo = ? AND taglia = ?",
            (quantita, articolo, taglia),
        )
        con.execute(
            "UPDATE richieste SET stato = 'consegnata' WHERE id = ?", (id_richiesta,)
        )
    return None


def elimina_consegnate():
    """Cancella le richieste già consegnate (con i nomi). Restituisce quante."""
    with db() as con:
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


def testo_informativa():
    """Testo dell'informativa privacy mostrato nel modulo."""
    dati = "il tuo nome e cognome"
    if CHIEDI_CONTATTO:
        dati += " e un recapito (telefono o e-mail)"
    return (
        f"**Chi tratta i dati:** {TITOLARE}. Contatto: {CONTATTO_PRIVACY}.\n\n"
        f"**Quali dati:** raccogliamo solo {dati}, insieme alla richiesta "
        "(tipo di capo, taglia e quantità).\n\n"
        "**Perché:** per organizzare la distribuzione dell'abbigliamento e "
        "sapere a chi consegnarlo.\n\n"
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
        contatto = ""
        if CHIEDI_CONTATTO:
            contatto = st.text_input("Telefono o e-mail")
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
            if not nome.strip() or (CHIEDI_CONTATTO and not contatto.strip()):
                st.error("Compila tutti i campi richiesti.")
            elif not richieste:
                st.error("Scegli almeno un articolo.")
            elif not accetto:
                st.error("Per inviare devi spuntare la casella sull'informativa.")
            else:
                salva_richiesta(nome.strip(), contatto.strip(), richieste)
                st.success("Richiesta inviata, grazie!")


# ---------- Pagina amministratore ----------
def pagina_admin():
    st.title("👕 Area amministratore")
    tab_magazzino, tab_richieste = st.tabs(["Magazzino", "Richieste"])

    with tab_magazzino:
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
            st.dataframe(giacenze_tab, use_container_width=True)

    with tab_richieste:
        rich = leggi_richieste()
        if rich.empty:
            st.info("Nessuna richiesta ricevuta.")
        else:
            in_attesa = rich[rich["stato"] == "in attesa"]
            richiesti = tabella(in_attesa, "quantita")
            giacenze = tabella(leggi_magazzino(), "quantita")
            da_ordinare = (richiesti - giacenze).clip(lower=0)

            st.subheader("Totale richiesto per taglia")
            st.caption("Solo richieste in attesa di consegna")
            st.dataframe(con_totali(richiesti), use_container_width=True)

            st.subheader("Da ordinare")
            st.caption("Richiesto meno quanto hai già in magazzino")
            st.dataframe(con_totali(da_ordinare), use_container_width=True)

            st.subheader("Elenco richieste")
            st.dataframe(rich, use_container_width=True, hide_index=True)
            if not in_attesa.empty:
                id_sel = st.selectbox(
                    "Segna come consegnata (ID richiesta)", in_attesa["id"]
                )
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
                    f"Confermo: cancellare {len(consegnate)} righe già consegnate "
                    "(nomi compresi)"
                )
                if st.button("Cancella richieste consegnate"):
                    if conferma:
                        elimina_consegnate()
                        st.rerun()
                    else:
                        st.warning("Spunta prima la casella di conferma.")


# ---------- Avvio ----------
st.set_page_config(page_title="Abbigliamento", page_icon="👕")

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
                    if pwd == PASSWORD:
                        st.session_state.admin = True
                        st.rerun()
                    else:
                        st.error("Password errata")

if st.session_state.admin:
    pagina_admin()
else:
    pagina_pubblica()