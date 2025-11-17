# checker.py
import re
import os
from typing import Optional

import requests
from bs4 import BeautifulSoup

from models import AuditResult
from utils import normalize_url

# Optional: PageSpeed / Lighthouse via API -> hier nur Platzhalter

API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise RuntimeError("GOOGLE_API_KEY fehlt. Bitte in .env setzen.")

EMAIL_REGEX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def check_https(url: str) -> bool:
    """
    Prüft grob, ob die Seite über HTTPS erreichbar ist.
    """
    normalized = normalize_url(url)
    return normalized.startswith("https://")


def fetch_html(url: str) -> Optional[str]:
    """
    Holt das HTML einer Seite. Einfach gehalten, mit Timeout.
    """
    try:
        normalized = normalize_url(url)
        resp = requests.get(normalized, timeout=10)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[WARN] Fehler beim Abruf von {url}: {e}")
        return None


def detect_viewport(soup: BeautifulSoup) -> bool:
    tag = soup.find("meta", attrs={"name": "viewport"})
    return tag is not None


def detect_cms(html: str) -> Optional[str]:
    """
    Sehr einfache Heuristik, kann später ausgebaut werden.
    """
    lower = html.lower()
    if "wp-content" in html or "wordpress" in lower:
        return "WordPress"
    if "joomla" in lower:
        return "Joomla"
    if "shopify" in lower:
        return "Shopify"
    return None


def detect_contact_page(soup: BeautifulSoup) -> bool:
    """
    Sucht nach Links auf Kontakt-/Impressum-/Contact-Seiten.
    """
    keywords = ["kontakt", "impressum", "contact"]
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = (a.get_text() or "").lower()
        if any(k in href for k in keywords) or any(k in text for k in keywords):
            return True
    return False


def detect_email_and_phone(html: str) -> tuple[bool, bool]:
    """
    Sucht nach E-Mails und tel:-Links im HTML.
    """
    has_email = bool(EMAIL_REGEX.findall(html or ""))
    has_tel = "tel:" in (html or "").lower()
    return has_email, has_tel


def detect_online_booking(html: str) -> bool:
    """
    Sucht nach Hinweisen auf Online-Buchung / Terminvereinbarung.
    """
    lower = (html or "").lower()
    keywords = [
        "online buchen",
        "jetzt buchen",
        "termin buchen",
        "termin vereinbaren",
        "appointment",
        "book now",
        "reservation",
    ]
    widgets = [
        "calendly.com",
        "bookingkit",
        "treatwell",
        "fresha.com",
    ]
    if any(k in lower for k in keywords):
        return True
    if any(w in lower for w in widgets):
        return True
    return False


def detect_social_links(html: str) -> bool:
    lower = (html or "").lower()
    social_domains = [
        "instagram.com",
        "facebook.com",
        "fb.me",
        "linkedin.com",
        "tiktok.com",
        "youtube.com",
    ]
    return any(d in lower for d in social_domains)


def detect_analytics(html: str) -> bool:
    """
    Sehr einfache Heuristik für Google Analytics / Tag Manager / Meta Pixel.
    """
    text = html or ""
    patterns = [
        "gtag(",
        "googletagmanager.com",
        "analytics.js",
        "ga('create'",
        "fbq(",
    ]
    return any(p in text for p in patterns)


def compute_word_count(soup: BeautifulSoup) -> int:
    """
    Zählt grob die Wörter im sichtbaren Text.
    """
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    words = [w for w in text.split() if w.strip()]
    return len(words)


def fetch_performance_score(url: str) -> Optional[int]:
    """
    Ruft den mobilen Performance-Score (0–100) der Google PageSpeed Insights API ab.
    """
    if not API_KEY:
        print("[INFO] No API_KEY found, returning None.")
        return None

    api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    params = {
        "url": url,
        "strategy": "mobile",   # "mobile" or "desktop"
        "key": API_KEY,
    }

    try:
        resp = requests.get(api_url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        # Extract Lighthouse Performance Score
        score = (
            data.get("lighthouseResult", {})
            .get("categories", {})
            .get("performance", {})
            .get("score")
        )

        if score is None:
            return None

        # Lighthouse returns 0–1 float → convert to 0–100 int
        return int(score * 100)

    except Exception as e:
        print(f"[WARN] PSI API error for {url}: {e}")
        return None


def audit_website(url: str) -> AuditResult:
    audit = AuditResult(url=url)
    audit.has_https = check_https(url)

    html = fetch_html(url)
    if not html:
        audit.issues["no_html"] = True
        return audit

    soup = BeautifulSoup(html, "html.parser")

    # Basissignale
    audit.has_viewport = detect_viewport(soup)
    audit.cms = detect_cms(html)
    audit.performance_score = fetch_performance_score(url)

    # Erweiterte Website-Signale
    audit.has_contact_page = detect_contact_page(soup)
    audit.has_email_on_site, audit.has_clickable_phone = detect_email_and_phone(html)
    audit.has_online_booking = detect_online_booking(html)
    audit.has_social_links = detect_social_links(html)
    audit.has_analytics = detect_analytics(html)
    audit.content_word_count = compute_word_count(soup)

    # Issues-Flags
    audit.issues["no_viewport"] = audit.has_viewport is False
    audit.issues["no_https"] = not audit.has_https
    audit.issues["unknown_cms"] = audit.cms is None
    audit.issues["no_contact_page"] = audit.has_contact_page is False
    audit.issues["no_contact_info"] = (
        audit.has_email_on_site is False and audit.has_clickable_phone is False
    )
    audit.issues["low_performance"] = (
        audit.performance_score is not None and audit.performance_score < 50
    )

    return audit
