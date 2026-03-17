import re
from dataclasses import dataclass


@dataclass
class ModerationResult:
    status: str
    score: float
    reason: str
    requires_human_review: bool = False


PROHIBITED_WORDS = {
    "badword1",
    "badword2",
}

REVIEW_WORDS = {
    "borderlineword1",
    "borderlineword2",
}


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\W_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def contains_word(text: str, words: set[str]) -> str | None:
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return word
    return None


def moderate_text(text: str, context: str = "general") -> ModerationResult:
    if not text or not text.strip():
        return ModerationResult(
            status="approved",
            score=0.0,
            reason=""
        )

    normalized = normalize_text(text)

    blocked_word = contains_word(normalized, PROHIBITED_WORDS)
    if blocked_word:
        # For message content, we may want pending instead of outright reject
        if context == "message_content":
            return ModerationResult(
                status="pending",
                score=0.85,
                reason=f"Possible inappropriate language in submitted message content: {blocked_word}",
                requires_human_review=True
            )

        return ModerationResult(
            status="rejected",
            score=0.95,
            reason=f"Blocked for prohibited language: {blocked_word}",
            requires_human_review=False
        )

    review_word = contains_word(normalized, REVIEW_WORDS)
    if review_word:
        return ModerationResult(
            status="pending",
            score=0.65,
            reason=f"Possible inappropriate language requires review: {review_word}",
            requires_human_review=True
        )

    return ModerationResult(
        status="approved",
        score=0.05,
        reason=""
    )