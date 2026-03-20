import re
from dataclasses import dataclass, field


@dataclass
class PIIMatch:
    entity_type: str
    value: str


@dataclass
class PIIDetectionResult:
    detected: bool
    status: str
    review_required: bool
    notes: str = ""
    matches: list[PIIMatch] = field(default_factory=list)


EMAIL_PATTERN = re.compile(
    r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'
)

PHONE_PATTERN = re.compile(
    r'(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})'
)

SSN_PATTERN = re.compile(
    r'\b\d{3}-\d{2}-\d{4}\b'
)

CARD_PATTERN = re.compile(
    r'\b(?:\d[ -]*?){13,19}\b'
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    digits = re.sub(r'\D', '', value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def luhn_check(number: str) -> bool:
    digits = re.sub(r'\D', '', number)

    if not 13 <= len(digits) <= 19:
        return False

    total = 0
    reverse_digits = digits[::-1]

    for index, digit_char in enumerate(reverse_digits):
        digit = int(digit_char)

        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9

        total += digit

    return total % 10 == 0


def find_emails(text: str) -> list[PIIMatch]:
    return [
        PIIMatch(entity_type="email", value=match.group().strip())
        for match in EMAIL_PATTERN.finditer(text)
    ]


def find_phone_numbers(text: str) -> list[PIIMatch]:
    matches = []

    for match in PHONE_PATTERN.finditer(text):
        value = match.group().strip()
        digits = re.sub(r'\D', '', value)

        if len(digits) in (10, 11):
            matches.append(PIIMatch(entity_type="phone", value=value))

    return matches


def find_ssns(text: str) -> list[PIIMatch]:
    return [
        PIIMatch(entity_type="ssn", value=match.group().strip())
        for match in SSN_PATTERN.finditer(text)
    ]


def find_card_numbers(text: str) -> list[PIIMatch]:
    matches = []

    for match in CARD_PATTERN.finditer(text):
        value = match.group().strip()
        if luhn_check(value):
            matches.append(PIIMatch(entity_type="card", value=value))

    return matches


def extract_allowed_sender_identifiers(sender: str) -> dict[str, set[str]]:
    allowed = {
        "email": set(),
        "phone": set(),
    }

    if not sender or not sender.strip():
        return allowed

    for match in find_emails(sender):
        allowed["email"].add(normalize_email(match.value))

    for match in find_phone_numbers(sender):
        normalized = normalize_phone(match.value)
        if normalized:
            allowed["phone"].add(normalized)

    return allowed


def filter_sender_matches(
    matches: list[PIIMatch],
    sender: str | None = None
) -> tuple[list[PIIMatch], list[PIIMatch]]:
    if not sender:
        return matches, []

    allowed = extract_allowed_sender_identifiers(sender)

    kept = []
    removed = []

    for match in matches:
        if match.entity_type == "email":
            if normalize_email(match.value) in allowed["email"]:
                removed.append(match)
                continue

        elif match.entity_type == "phone":
            if normalize_phone(match.value) in allowed["phone"]:
                removed.append(match)
                continue

        kept.append(match)

    return kept, removed


def detect_pii(
    text: str,
    context: str = "general",
    sender: str | None = None
) -> PIIDetectionResult:
    if not text or not text.strip():
        return PIIDetectionResult(
            detected=False,
            status="approved",
            review_required=False,
            notes="",
            matches=[]
        )

    cleaned_text = normalize_whitespace(text)

    matches: list[PIIMatch] = []
    matches.extend(find_emails(cleaned_text))
    matches.extend(find_phone_numbers(cleaned_text))
    matches.extend(find_ssns(cleaned_text))
    matches.extend(find_card_numbers(cleaned_text))

    matches, sender_matches = filter_sender_matches(matches, sender=sender)

    if not matches:
        return PIIDetectionResult(
            detected=False,
            status="approved",
            review_required=False,
            notes="",
            matches=[]
        )

    entity_counts = {}
    for match in matches:
        entity_counts[match.entity_type] = entity_counts.get(match.entity_type, 0) + 1

    summary_parts = [
        f"{count} {entity_type}"
        for entity_type, count in entity_counts.items()
    ]
    notes = "Detected possible PII: " + ", ".join(summary_parts)

    high_risk_types = {"ssn", "card"}
    found_high_risk = any(match.entity_type in high_risk_types for match in matches)

    if context == "sender":
        if found_high_risk:
            return PIIDetectionResult(
                detected=True,
                status="pending",
                review_required=True,
                notes=notes,
                matches=matches
            )

        return PIIDetectionResult(
            detected=True,
            status="approved",
            review_required=False,
            notes=notes,
            matches=matches
        )

    if found_high_risk:
        return PIIDetectionResult(
            detected=True,
            status="pending",
            review_required=True,
            notes=notes,
            matches=matches
        )

    return PIIDetectionResult(
        detected=True,
        status="pending",
        review_required=True,
        notes=notes,
        matches=matches
    )