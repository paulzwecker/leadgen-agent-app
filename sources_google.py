# sources_google.py
import os
import time
from typing import List, Dict, Optional
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

# .env laden
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise RuntimeError("GOOGLE_API_KEY fehlt. Bitte in .env setzen.")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = DATA_DIR / "input_companies.csv"


# --------------------------------------------------------
# 1) Google Places Text Search
# --------------------------------------------------------

GOOGLE_PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def google_text_search(
    query: str,
    region: Optional[str] = None,
    max_results: int = 60,
) -> List[Dict]:
    """
    Nutzt die Places Text Search API, um Unternehmen zu finden.
    query z.B.: "Friseur in Berlin" oder "Restaurant Köln".
    """
    params = {
        "key": API_KEY,
        "query": query,
    }
    if region:
        params["region"] = region

    results: List[Dict] = []
    next_page_token: Optional[str] = None

    while True:
        if next_page_token:
            params["pagetoken"] = next_page_token
            # Die API braucht kurz, bis der Token aktiv ist
            time.sleep(2)

        resp = requests.get(GOOGLE_PLACES_TEXT_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            print(f"[WARN] API-Status: {status}, data: {data}")
            break

        batch = data.get("results", [])
        results.extend(batch)

        # Abbruchbedingungen
        if len(results) >= max_results:
            results = results[:max_results]
            break

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

    return results


# --------------------------------------------------------
# 2) Details-API pro Place, um Website & Phone zu holen
# --------------------------------------------------------

def google_place_details(place_id: str, fields: Optional[List[str]] = None) -> Dict:
    """
    Holt Details zu einem Place (Website, Telefonnummer, Öffnungszeiten, etc.)
    fields: Liste der Felder, z.B. ["name", "formatted_phone_number", "website"]
    """
    if fields is None:
        fields = [
            "name",
            "formatted_address",
            "formatted_phone_number",
            "international_phone_number",
            "website",
            "opening_hours",
            "url",
            "rating",
            "user_ratings_total",
            "price_level",
            "business_status",
            "types",
        ]

    params = {
        "key": API_KEY,
        "place_id": place_id,
        "fields": ",".join(fields),
    }

    resp = requests.get(GOOGLE_PLACES_DETAILS_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        print(f"[WARN] Details-Status für {place_id}: {data.get('status')}")
        return {}

    return data.get("result", {})


# --------------------------------------------------------
# 3) Optional: E-Mail von der Website parsen
# --------------------------------------------------------

EMAIL_REGEX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def fetch_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[WARN] Fehler beim Abruf von {url}: {e}")
        return None


def find_emails_in_html(html: str) -> List[str]:
    return list(set(EMAIL_REGEX.findall(html or "")))


def try_find_email_on_site(base_url: str) -> Optional[str]:
    """
    Sehr grobe Heuristik:
    - Startseite nach E-Mail scannen
    - /kontakt, /impressum suchen und ebenfalls scannen
    """
    html = fetch_html(base_url)
    if not html:
        return None

    emails = find_emails_in_html(html)
    if emails:
        return emails[0]  # erste E-Mail reicht

    # Links auf Kontakt-/Impressum-Seiten suchen
    soup = BeautifulSoup(html, "html.parser")
    candidate_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = (a.get_text() or "").lower()

        if any(keyword in href for keyword in ["kontakt", "impressum", "contact"]):
            candidate_links.append(a["href"])
        elif any(keyword in text for keyword in ["kontakt", "impressum", "contact"]):
            candidate_links.append(a["href"])

    for link in candidate_links:
        full_url = urljoin(base_url, link)
        sub_html = fetch_html(full_url)
        if not sub_html:
            continue
        emails = find_emails_in_html(sub_html)
        if emails:
            return emails[0]

    return None


# --------------------------------------------------------
# 4) Hauptfunktion: Unternehmen suchen & CSV bauen
# --------------------------------------------------------

def build_input_csv_from_query(
    query: str,
    region: Optional[str] = None,
    max_results: int = 60,
    try_scrape_email: bool = False,
    output_file: Path = OUTPUT_FILE,
):
    """
    Sucht Unternehmen zu einem Suchstring und schreibt input_companies.csv.
    query z.B.: "Friseur in Berlin" oder "Zahnarzt München".
    """
    print(f"Suche Unternehmen zu: '{query}' ...")
    places = google_text_search(query=query, region=region, max_results=max_results)
    print(f"{len(places)} Treffer aus Text Search.")

    rows = []

    for idx, p in enumerate(places, start=1):
        place_id = p.get("place_id")
        name = p.get("name")
        address = p.get("formatted_address")
        # 'types' ist eine Liste von Kategorien
        types = p.get("types", [])

        print(f"[{idx}/{len(places)}] Hole Details für: {name} ...")

        details = google_place_details(place_id)
        website = details.get("website")
        phone = details.get("formatted_phone_number") or details.get(
            "international_phone_number"
        )

        rating = details.get("rating")
        user_ratings_total = details.get("user_ratings_total", 0)
        price_level = details.get("price_level")
        business_status = details.get("business_status")
        detail_types = details.get("types", []) or p.get("types", [])

        email = None
        if try_scrape_email and website:
            print(f"  -> versuche E-Mail auf {website} zu finden ...")
            email = try_find_email_on_site(website)

        row = {
            "name": name,
            "website": website or "",
            "phone": phone or "",
            "email": email or "",
            "address": address or details.get("formatted_address", ""),
            "google_place_id": place_id or "",
            "google_maps_url": details.get("url", ""),
            "types": ",".join(detail_types),
            # Neue Felder:
            "rating": rating if rating is not None else "",
            "user_ratings_total": user_ratings_total,
            "price_level": price_level if price_level is not None else "",
            "business_status": business_status or "",
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # Nur Unternehmen mit Website behalten (optional – kannst du entfernen)
    df = df[df["website"].str.len() > 0]

    df.to_csv(output_file, index=False, encoding="utf-8")
    print(f"Fertig. CSV gespeichert in: {output_file}")


if __name__ == "__main__":
    # Beispiel: Friseure in Berlin
    build_input_csv_from_query(
        query="Friseur in Berlin",
        region="de",
        max_results=60,
        try_scrape_email=True,
    )
