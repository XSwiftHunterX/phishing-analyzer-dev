import re
from urllib.parse import urlparse

from analyzer.models import Message


MIN_WORD_LENGTH = 4
COMMON_WORDS = {
    "about", "account", "alert", "click", "code", "confirm", "customer",
    "email", "follow", "hello", "information", "kindly", "limited", "login",
    "message", "notice", "number", "online", "password", "phone", "please",
    "reply", "secure", "service", "support", "system", "thanks", "update",
    "urgent", "verify", "warning", "your", "yours"
}


def normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_word_set(text):
    words = normalize_text(text).split()
    return {
        word for word in words
        if len(word) >= MIN_WORD_LENGTH and word not in COMMON_WORDS
    }


def normalized_list(values):
    if not values:
        return set()

    cleaned = set()
    for value in values:
        normalized = str(value).strip().lower()
        if normalized:
            cleaned.add(normalized)
    return cleaned


def normalize_sender(sender):
    return (sender or "").strip().lower()


def normalize_platform(platform):
    return (platform or "").strip().lower()


def normalize_message_type(message_type):
    return (message_type or "").strip().lower()


def normalize_domain(value):
    value = (value or "").strip().lower()
    if not value:
        return ""

    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    value = value.lstrip("www.")
    return value


def extract_domain_from_url(url):
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return normalize_domain(parsed.netloc)
    except Exception:
        return ""


def normalize_url(url):
    url = (url or "").strip().lower()
    if not url:
        return ""

    parsed_domain = extract_domain_from_url(url)
    if parsed_domain:
        return url.rstrip("/")

    return url


def expanded_domains(domains, urls):
    domain_set = {normalize_domain(domain) for domain in domains if normalize_domain(domain)}

    for url in urls:
        domain = extract_domain_from_url(url)
        if domain:
            domain_set.add(domain)

    return domain_set


def platform_similarity_score(source_platform, candidate_platform):
    if not source_platform or not candidate_platform:
        return 0, None

    if source_platform == candidate_platform:
        return 10, "Same platform"

    source_tokens = set(source_platform.split())
    candidate_tokens = set(candidate_platform.split())
    overlap = source_tokens.intersection(candidate_tokens)

    if overlap:
        return 5, "Similar platform"

    return 0, None


def add_reason(reasons, reason):
    if reason and reason not in reasons:
        reasons.append(reason)


def build_analysis_features(analysis):
    features = {
        "urls": set(),
        "domains": set(),
        "emails": set(),
        "phone_numbers": set(),
        "brand": "",
        "scam_category": "",
        "requested_action": "",
        "brand_display": "",
        "scam_category_display": "",
        "requested_action_display": "",
    }

    if not analysis:
        return features

    urls = {normalize_url(url) for url in normalized_list(analysis.detected_urls)}
    urls.discard("")

    domains = expanded_domains(
        normalized_list(analysis.detected_domains),
        urls
    )

    emails = normalized_list(analysis.detected_emails)
    phone_numbers = normalized_list(analysis.detected_phone_numbers)

    brand_display = (analysis.impersonated_brand or "").strip()
    scam_category_display = (analysis.scam_category or "").strip()
    requested_action_display = (analysis.requested_action or "").strip()

    features.update({
        "urls": urls,
        "domains": domains,
        "emails": emails,
        "phone_numbers": phone_numbers,
        "brand": brand_display.lower(),
        "scam_category": scam_category_display.lower(),
        "requested_action": requested_action_display.lower(),
        "brand_display": brand_display,
        "scam_category_display": scam_category_display,
        "requested_action_display": requested_action_display,
    })

    return features


def score_shared_indicator(shared_values, base_score, per_extra_match=5, max_score=None):
    count = len(shared_values)
    if count == 0:
        return 0

    score = base_score + max(0, count - 1) * per_extra_match

    if max_score is not None:
        score = min(score, max_score)

    return score


def find_similar_messages(message, limit=5):
    """
    Finds similar messages using:
    - same sender
    - matching message type
    - matching platform
    - cross-checks between sender field and AI-extracted indicators
    - matching AI-extracted indicators
    - overlapping content wording
    """

    queryset = Message.objects.filter(
        is_removed=False,
        moderation_status="approved"
    ).exclude(id=message.id).select_related("ai_analysis")

    results = []

    source_sender = normalize_sender(message.sender)
    source_type = normalize_message_type(message.message_type)
    source_platform = normalize_platform(getattr(message, "platform", ""))
    source_content_words = clean_word_set(message.message_content)

    source_features = build_analysis_features(getattr(message, "ai_analysis", None))
    source_urls = source_features["urls"]
    source_domains = source_features["domains"]
    source_emails = source_features["emails"]
    source_phone_numbers = source_features["phone_numbers"]
    source_brand = source_features["brand"]
    source_scam_category = source_features["scam_category"]
    source_requested_action = source_features["requested_action"]

    for candidate in queryset:
        score = 0
        reasons = []

        candidate_sender = normalize_sender(candidate.sender)
        candidate_type = normalize_message_type(candidate.message_type)
        candidate_platform = normalize_platform(getattr(candidate, "platform", ""))
        candidate_content_words = clean_word_set(candidate.message_content)

        candidate_features = build_analysis_features(getattr(candidate, "ai_analysis", None))
        candidate_urls = candidate_features["urls"]
        candidate_domains = candidate_features["domains"]
        candidate_emails = candidate_features["emails"]
        candidate_phone_numbers = candidate_features["phone_numbers"]
        candidate_brand = candidate_features["brand"]
        candidate_scam_category = candidate_features["scam_category"]
        candidate_requested_action = candidate_features["requested_action"]

        # --- direct sender match ---
        if source_sender and candidate_sender and source_sender == candidate_sender:
            score += 50
            add_reason(reasons, "Same sender")

        # --- message type match ---
        if source_type and candidate_type and source_type == candidate_type:
            score += 8
            add_reason(reasons, "Same message type")

        # --- platform match ---
        platform_score, platform_reason = platform_similarity_score(
            source_platform,
            candidate_platform,
        )
        score += platform_score
        add_reason(reasons, platform_reason)

        # --- cross-check sender field against extracted indicators ---
        if source_sender:
            if source_sender in candidate_emails:
                score += 40
                add_reason(reasons, "Sender matches extracted email")
            if normalize_domain(source_sender) and normalize_domain(source_sender) in candidate_domains:
                score += 30
                add_reason(reasons, "Sender matches extracted domain")
            if source_sender in candidate_phone_numbers:
                score += 40
                add_reason(reasons, "Sender matches extracted phone number")

        if candidate_sender:
            if candidate_sender in source_emails:
                score += 40
                add_reason(reasons, "Extracted email matches sender")
            if normalize_domain(candidate_sender) and normalize_domain(candidate_sender) in source_domains:
                score += 30
                add_reason(reasons, "Extracted domain matches sender")
            if candidate_sender in source_phone_numbers:
                score += 40
                add_reason(reasons, "Extracted phone number matches sender")

        # --- exact extracted indicator matches ---
        shared_urls = source_urls.intersection(candidate_urls)
        if shared_urls:
            score += score_shared_indicator(shared_urls, base_score=45, per_extra_match=10, max_score=70)
            add_reason(reasons, "Same suspicious URL")

        shared_domains = source_domains.intersection(candidate_domains)
        if shared_domains:
            score += score_shared_indicator(shared_domains, base_score=35, per_extra_match=6, max_score=55)
            add_reason(reasons, "Same domain")

        shared_emails = source_emails.intersection(candidate_emails)
        if shared_emails:
            score += score_shared_indicator(shared_emails, base_score=35, per_extra_match=8, max_score=60)
            add_reason(reasons, "Same email address")

        shared_phone_numbers = source_phone_numbers.intersection(candidate_phone_numbers)
        if shared_phone_numbers:
            score += score_shared_indicator(shared_phone_numbers, base_score=40, per_extra_match=8, max_score=60)
            add_reason(reasons, "Same phone number")

        if source_brand and candidate_brand and source_brand == candidate_brand:
            score += 20
            add_reason(
                reasons,
                f"Same impersonated brand: {candidate_features['brand_display']}"
            )

        if source_scam_category and candidate_scam_category and source_scam_category == candidate_scam_category:
            score += 15
            add_reason(
                reasons,
                f"Same scam category: {candidate_features['scam_category_display']}"
            )

        if (
            source_requested_action
            and candidate_requested_action
            and source_requested_action == candidate_requested_action
        ):
            score += 10
            add_reason(
                reasons,
                f"Same requested action: {candidate_features['requested_action_display']}"
            )

        # --- content similarity fallback ---
        overlap = source_content_words.intersection(candidate_content_words)
        overlap_count = len(overlap)

        if overlap_count >= 3:
            wording_score = min(overlap_count * 4, 24)
            score += wording_score

            if overlap_count >= 6:
                add_reason(reasons, "Very similar wording")
            else:
                add_reason(reasons, "Similar wording")

        if score >= 15:
            results.append({
                "message": candidate,
                "score": score,
                "reasons": reasons,
            })

    results.sort(
        key=lambda item: (
            item["score"],
            len(item["reasons"]),
            getattr(item["message"], "submission_date", None) or getattr(item["message"], "id", 0),
        ),
        reverse=True,
    )

    return results[:limit]