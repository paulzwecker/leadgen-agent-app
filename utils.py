# utils.py
from urllib.parse import urlparse
from typing import Optional, Dict

from models import AuditResult


def normalize_url(url: str) -> str:
    """
    Sorgt dafür, dass eine URL ein Schema hat (https://...), entfernt Spaces etc.
    """
    url = url.strip()
    if not url:
        return url

    parsed = urlparse(url)
    if not parsed.scheme:
        # Standard: https annehmen
        url = "https://" + url

    return url


def compute_basic_score(audit: AuditResult) -> int:
    """
    Einfacher Website-Pain-Score.
    """
    score = 0

    if not audit.has_https:
        score += 3
    if not audit.has_viewport:
        score += 3
    if audit.cms is None:
        score += 1
    if audit.performance_score is not None and audit.performance_score < 50:
        score += 3

    # Kontaktierbarkeit
    if audit.has_contact_page is False:
        score += 2
    if audit.has_email_on_site is False and audit.has_clickable_phone is False:
        score += 2

    return score


def compute_extended_score(
    audit: AuditResult, place_info: Optional[Dict] = None
) -> int:
    """
    Erweiterter Score: Website-Pain + Business-Fit (Bewertungen, price_level).
    """
    score = compute_basic_score(audit)

    if place_info:
        status = place_info.get("business_status")
        if status and status != "OPERATIONAL":
            # Geschäft ist (vorübergehend) geschlossen -> als Lead uninteressant
            return -999

        rating = place_info.get("rating") or 0
        reviews = place_info.get("user_ratings_total") or 0
        price_level = place_info.get("price_level")

        if rating >= 4.0 and reviews >= 20:
            score += 3
        if reviews >= 100:
            score += 1
        if price_level is not None and price_level != "" and price_level >= 2:
            score += 1

    return score
