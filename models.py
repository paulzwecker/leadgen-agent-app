# models.py
from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class Company:
    name: str
    website: str
    raw_data: Dict = field(default_factory=dict)

@dataclass
class AuditResult:
    url: str
    has_https: bool = False
    has_viewport: bool = False
    cms: Optional[str] = None
    performance_score: Optional[int] = None

    # Neue Website-Signale
    has_contact_page: Optional[bool] = None
    has_email_on_site: Optional[bool] = None
    has_clickable_phone: Optional[bool] = None
    has_online_booking: Optional[bool] = None
    has_social_links: Optional[bool] = None
    has_analytics: Optional[bool] = None
    content_word_count: Optional[int] = None

    # Scores
    score: int = 0              # historisch, kannst du als Alias lassen
    score_basic: int = 0
    score_extended: int = 0

    issues: Dict[str, bool] = field(default_factory=dict)
