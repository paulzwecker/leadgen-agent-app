# app.py
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
import re

from sources_google import build_input_csv_from_query
from checker import audit_website
from utils import compute_basic_score, compute_extended_score
from models import Company

DATA_DIR = Path("data")

st.set_page_config(
    page_title="Lead Generator",
    layout="wide",
)

# ----------------------------------------------------------------------
# Session State initialisieren
# ----------------------------------------------------------------------
if "df_input" not in st.session_state:
    st.session_state["df_input"] = None
if "df_leads" not in st.session_state:
    st.session_state["df_leads"] = None
if "current_run_dir" not in st.session_state:
    st.session_state["current_run_dir"] = None
if "filter_text" not in st.session_state:
    st.session_state["filter_text"] = ""
if "min_score" not in st.session_state:
    st.session_state["min_score"] = 0
if "score_metric" not in st.session_state:
    st.session_state["score_metric"] = None


def reset_filters():
    st.session_state["filter_text"] = ""
    st.session_state["min_score"] = 0
    # score_metric lassen wir, damit die Auswahl erhalten bleibt


st.title("🚀 Freelance Lead Generator – Websites mit Optimierungspotenzial finden")

st.markdown(
    """
Dieses Tool hilft dir dabei, aus **Google Maps / Google Places** und einer
automatischen Website-Prüfung eine **Lead-Liste** zu bauen.

- Jede Suche wird jetzt in einem eigenen Unterordner gespeichert, z.B.  
  `data/20251117_karlsruhe_friseur_60/`
- Du kannst vorhandene Läufe auswählen und wieder anzeigen lassen.
"""
)

# ----------------------------------------------------------------------
# Helper: Slug / Run-ID
# ----------------------------------------------------------------------


def slugify(value: str) -> str:
    """Einfache Slug-Funktion für Ordnernamen."""
    value = value.strip().lower()
    # Umlaute ersetzen
    value = (
        value.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    # Leerzeichen -> Bindestrich
    value = re.sub(r"\s+", "-", value)
    # Nur noch a-z0-9 und -
    value = re.sub(r"[^a-z0-9\\-]", "", value)
    return value or "unknown"


def make_run_id(city: str, sector: str, limit: int) -> str:
    """Erzeugt eine Run-ID wie 20251117_karlsruhe_friseur_60."""
    today = datetime.today().strftime("%Y%m%d")
    return f"{today}_{slugify(city)}_{slugify(sector)}_{int(limit)}"


def parse_run_dir_name(name: str):
    """
    Erwartet: YYYYMMDD_city_sector_limit
    Gibt (label, date_str, city, sector, limit) zurück.
    """
    parts = name.split("_")
    if len(parts) < 4:
        return None

    date_raw = parts[0]
    city_slug = parts[1]
    sector_slug = "_".join(parts[2:-1])  # falls mal mehr als 4 parts
    limit_str = parts[-1]

    try:
        date_fmt = datetime.strptime(date_raw, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        date_fmt = date_raw

    def deslug(s: str) -> str:
        return s.replace("-", " ").title()

    city = deslug(city_slug)
    sector = deslug(sector_slug)

    label = f"{date_fmt} – {city} / {sector} / {limit_str}"
    return label, date_fmt, city, sector, limit_str


# ----------------------------------------------------------------------
# Helper: Daten laden / Audit
# ----------------------------------------------------------------------


def load_companies_from_csv(path: Path) -> list[Company]:
    df = pd.read_csv(path)
    companies: list[Company] = []
    for _, row in df.iterrows():
        website = str(row.get("website", "")).strip()
        name = str(row.get("name", "")).strip()
        if not website:
            continue
        raw = row.to_dict()
        companies.append(Company(name=name, website=website, raw_data=raw))
    return companies


def run_audit_on_companies(input_csv: Path, leads_output_path: Path):
    """Auditiert Websites aus input_csv und speichert leads_output_path."""
    df_in = pd.read_csv(input_csv)
    companies = load_companies_from_csv(input_csv)

    results = []

    progress = st.progress(0.0, text="Prüfe Websites ...")
    total = len(companies) if companies else 1

    for idx, company in enumerate(companies, start=1):
        progress.progress(idx / total, text=f"Prüfe {company.name} – {company.website}")
        audit = audit_website(company.website)

        # passendes Place-Info-Row aus df_in holen
        place_row = df_in[df_in["website"] == company.website].iloc[0]

        place_info = {
            "rating": place_row.get("rating"),
            "user_ratings_total": place_row.get("user_ratings_total"),
            "price_level": place_row.get("price_level"),
            "business_status": place_row.get("business_status"),
        }

        score_basic = compute_basic_score(audit)
        score_extended = compute_extended_score(audit, place_info)

        audit.score_basic = score_basic
        audit.score_extended = score_extended

        row = {
            "name": company.name,
            "website": company.website,
            # Website-Signale
            "has_https": audit.has_https,
            "has_viewport": audit.has_viewport,
            "cms": audit.cms,
            "performance_score": audit.performance_score,
            "has_contact_page": audit.has_contact_page,
            "has_email_on_site": audit.has_email_on_site,
            "has_clickable_phone": audit.has_clickable_phone,
            "has_online_booking": audit.has_online_booking,
            "has_social_links": audit.has_social_links,
            "has_analytics": audit.has_analytics,
            "content_word_count": audit.content_word_count,
            # Scores
            "score_basic": score_basic,
            "score_extended": score_extended,
            # Issues-Flags als Text
            "issues": ";".join([k for k, v in audit.issues.items() if v]),
        }

        # Google Places Infos aus df_in übernehmen
        for col in [
            "phone",
            "email",
            "address",
            "google_maps_url",
            "types",
            "rating",
            "user_ratings_total",
            "price_level",
            "business_status",
        ]:
            if col in df_in.columns:
                row[col] = place_row.get(col)

        results.append(row)

    progress.empty()

    df_out = pd.DataFrame(results)
    df_out.sort_values(by="score_extended", ascending=False, inplace=True)
    leads_output_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(leads_output_path, index=False, encoding="utf-8")

    return df_in, df_out


def show_results(df_input: pd.DataFrame, df_leads: pd.DataFrame, run_dir: Path):
    """Shared UI für Filter + Tabellen, inkl. Info zu Run-Pfad."""
    st.subheader("📊 Tabellen & Filter")
    st.caption(f"Aktueller Run-Ordner: `{run_dir}`")

    col1, col2 = st.columns([2, 1])

    with col1:
        text_filter = st.text_input(
            "Filter (Name / Website enthält ...)",
            value=st.session_state.get("filter_text", ""),
            key="filter_text",
            placeholder="z.B. 'haare', 'müller', 'praxis' ...",
        )
    with col2:
        # Verfügbare Score-Spalten
        available_score_cols = [
            col
            for col in ["score_extended", "score_basic"]
            if col in df_leads.columns
        ]

        score_metric = None
        max_score_val = 10

        if available_score_cols:
            # Score-Metrik-Auswahl
            score_metric = st.selectbox(
                "Score-Metrik",
                options=available_score_cols,
                key="score_metric",
            )
            if not score_metric:
                score_metric = available_score_cols[0]

            if not df_leads.empty:
                max_score_val = int(df_leads["score_extended"].max())
            else:
                max_score_val = 10

            min_score = st.slider(
                "Min. Score (nur für Leads-Tabelle)",
                min_value=min(0, max_score_val),
                max_value=max_score_val,
                key="min_score",
            )
        else:
            score_metric = None
            min_score = 0

    # Reset-Button unter den Filtern
    st.button("🔄 Filter zurücksetzen", on_click=reset_filters)

    tab1, tab2 = st.tabs(["📥 Rohdaten (Input)", "🎯 Leads (Audited)"])

    # ---- Tab 1: Input -------------------------------------------------
    with tab1:
        st.markdown("**Unternehmen aus Google Places (input_companies.csv)**")
        df_in_display = df_input.copy()

        if text_filter:
            mask = (
                df_in_display["name"].fillna("").str.contains(text_filter, case=False)
                | df_in_display["website"]
                .fillna("")
                .str.contains(text_filter, case=False)
            )
            df_in_display = df_in_display[mask]

        st.dataframe(df_in_display, use_container_width=True)

    # ---- Tab 2: Leads (Output) ----------------------------------------
    with tab2:
        st.markdown("**Audited Leads mit Score (leads_scored.csv)**")
        df_leads_display = df_leads.copy()

        # Text-Filter
        if text_filter:
            mask = (
                df_leads_display["name"]
                .fillna("")
                .str.contains(text_filter, case=False)
                | df_leads_display["website"]
                .fillna("")
                .str.contains(text_filter, case=False)
            )
            df_leads_display = df_leads_display[mask]

        # Score-Filter
        if score_metric and score_metric in df_leads_display.columns:
            min_score_val = st.session_state.get("min_score", 0)
            df_leads_display = df_leads_display[
                df_leads_display[score_metric] >= min_score_val
            ]

        st.dataframe(df_leads_display, use_container_width=True)

        st.download_button(
            "📥 Leads als CSV herunterladen",
            data=df_leads_display.to_csv(index=False).encode("utf-8"),
            file_name="leads_scored_filtered.csv",
            mime="text/csv",
        )


# ----------------------------------------------------------------------
# Sidebar: Input & bestehende Runs
# ----------------------------------------------------------------------

with st.sidebar:
    st.header("🔎 Suchparameter (neuer Lauf)")

    city = st.text_input("Stadt", value="Karlsruhe")
    sector = st.text_input("Sektor / Branche", value="Friseur")
    limit = st.number_input(
        "Max. Anzahl Ergebnisse", min_value=10, max_value=200, value=60, step=10
    )

    try_scrape_email = st.checkbox(
        "Versuche E-Mail von der Website zu scrapen", value=True
    )

    st.markdown("---")
    st.header("📂 Gespeicherte Läufe")

    DATA_DIR.mkdir(exist_ok=True)
    run_dirs = [d for d in DATA_DIR.iterdir() if d.is_dir()]
    run_options = []

    for d in sorted(run_dirs, key=lambda p: p.name, reverse=True):
        parsed = parse_run_dir_name(d.name)
        if not parsed:
            continue
        label, date_fmt, city_lbl, sector_lbl, limit_lbl = parsed
        run_options.append((label, d))

    selected_run_dir = None
    if run_options:
        labels = [x[0] for x in run_options]
        selected_label = st.selectbox("Run auswählen", labels)
        label_to_dir = {lbl: d for lbl, d in run_options}
        selected_run_dir = label_to_dir[selected_label]
    else:
        st.caption("Noch keine gespeicherten Läufe gefunden.")

    st.markdown("---")
    run_button = st.button("🚀 Neuen Lauf: Daten holen & Leads analysieren")
    load_existing_button = st.button("📂 Ausgewählten Lauf laden")


# ----------------------------------------------------------------------
# Main logic: neuer Lauf ODER bestehenden Lauf laden
# ----------------------------------------------------------------------

if run_button:
    if not city or not sector:
        st.error("Bitte Stadt **und** Sektor eingeben.")
    else:
        run_id = make_run_id(city, sector, limit)
        run_dir = DATA_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        input_path = run_dir / "input_companies.csv"
        leads_path = run_dir / "leads_scored.csv"

        query = f"{sector} in {city}"
        st.info(f"Neuer Lauf: **{query}** – Ordner: `{run_dir}`")

        # 1) Companies aus Google Places holen und input_companies.csv bauen
        with st.spinner(
            "Hole Daten von Google Places und baue input_companies.csv ..."
        ):
            build_input_csv_from_query(
                query=query,
                region="de",
                max_results=int(limit),
                try_scrape_email=try_scrape_email,
                output_file=input_path,
            )

        if not input_path.exists():
            st.error(f"Es konnte keine input_companies.csv in {run_dir} erstellt werden.")
        else:
            st.success(f"input_companies.csv erstellt: {input_path}")

            # 2) Websites auditieren & Leads scoren
            with st.spinner("Prüfe Websites und berechne Lead-Score ..."):
                df_input, df_leads = run_audit_on_companies(input_path, leads_path)

            st.success(f"Leads analysiert. Ergebnis gespeichert unter: {leads_path}")

            # Ergebnisse in Session State speichern
            st.session_state["df_input"] = df_input
            st.session_state["df_leads"] = df_leads
            st.session_state["current_run_dir"] = run_dir

elif load_existing_button:
    if not selected_run_dir:
        st.error(
            "Es sind noch keine gespeicherten Läufe vorhanden oder keiner ausgewählt."
        )
    else:
        run_dir = selected_run_dir
        input_path = run_dir / "input_companies.csv"
        leads_path = run_dir / "leads_scored.csv"

        if not input_path.exists():
            st.error(
                f"In `{run_dir}` wurde keine input_companies.csv gefunden. "
                "Bitte zuerst einen neuen Lauf für diese Kombination starten."
            )
        elif not leads_path.exists():
            st.warning(
                f"input_companies.csv gefunden, aber {leads_path.name} existiert nicht.\n"
                "Ich prüfe jetzt die Websites und erstelle die Leads-Datei."
            )
            with st.spinner("Prüfe Websites und berechne Lead-Score ..."):
                df_input, df_leads = run_audit_on_companies(input_path, leads_path)
            st.success(f"Leads analysiert. Ergebnis gespeichert unter: {leads_path}")

            st.session_state["df_input"] = df_input
            st.session_state["df_leads"] = df_leads
            st.session_state["current_run_dir"] = run_dir
        else:
            st.success(f"Bestehender Lauf geladen: `{run_dir}`")
            df_input = pd.read_csv(input_path)
            df_leads = pd.read_csv(leads_path)

            st.session_state["df_input"] = df_input
            st.session_state["df_leads"] = df_leads
            st.session_state["current_run_dir"] = run_dir

# ----------------------------------------------------------------------
# Nach Buttons: Ergebnisse anzeigen, falls vorhanden
# ----------------------------------------------------------------------

if (
    st.session_state["df_input"] is not None
    and st.session_state["df_leads"] is not None
    and st.session_state["current_run_dir"] is not None
):
    show_results(
        st.session_state["df_input"],
        st.session_state["df_leads"],
        st.session_state["current_run_dir"],
    )
else:
    st.info(
        "Gib links Stadt, Sektor und Limit ein und klicke auf **„Neuen Lauf: Daten holen & Leads analysieren“** "
        "oder nutze **„Ausgewählten Lauf laden“**, um bereits gespeicherte Läufe anzuzeigen."
    )
