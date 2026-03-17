# analyzer/services/text_moderation.py

import re
from dataclasses import dataclass

BAD_WORDS = {
    "badword1",
    "badword2",
    "badword3",
}

HIGH_RISK_PATTERNS = [
    r"\bslur1\b",
    r"\bslur2\b",
]

@dataclass
class ModerationResult:
    status: str
    score: float
    reason: str
    requires_human_review: bool = False

def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\W_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def moderate_text(text: str) -> ModerationResult:
    if not text or not text.strip():
        return ModerationResult(
            status="approved",
            score=0.0,
            reason=""
        )

    normalized = normalize_text(text)

    for word in BAD_WORDS:
        if word in normalized:
            return ModerationResult(
                status="rejected",
                score=0.95,
                reason=f"Blocked for prohibited language: {word}",
                requires_human_review=False
            )

    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, normalized):
            return ModerationResult(
                status="pending",
                score=0.75,
                reason=f"Possible inappropriate content matched pattern: {pattern}",
                requires_human_review=True
            )

    return ModerationResult(
        status="approved",
        score=0.05,
        reason=""
    )