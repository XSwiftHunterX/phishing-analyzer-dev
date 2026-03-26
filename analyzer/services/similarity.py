import re

from analyzer.models import Message


def normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text


def clean_word_set(text):
    words = normalize_text(text).split()
    return {word for word in words if len(word) > 4}


def normalized_list(values):
    if not values:
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def normalize_sender(sender):
    return (sender or "").strip().lower()


def find_similar_messages(message, limit=5):
    """
    Finds similar messages using:
    - same sender
    - cross-checks between sender field and AI-extracted indicators
    - matching AI-extracted indicators
    - overlapping content wording
    """

    queryset = Message.objects.filter(
        is_removed=False,
        moderation_status="approved"
    ).exclude(id=message.id)

    results = []

    source_sender = normalize_sender(message.sender)
    source_content_words = clean_word_set(message.message_content)

    source_analysis = getattr(message, "ai_analysis", None)

    source_urls = set()
    source_domains = set()
    source_emails = set()
    source_phone_numbers = set()
    source_brand = ""
    source_scam_category = ""
    source_requested_action = ""

    if source_analysis:
        source_urls = normalized_list(source_analysis.detected_urls)
        source_domains = normalized_list(source_analysis.detected_domains)
        source_emails = normalized_list(source_analysis.detected_emails)
        source_phone_numbers = normalized_list(source_analysis.detected_phone_numbers)
        source_brand = (source_analysis.impersonated_brand or "").strip().lower()
        source_scam_category = (source_analysis.scam_category or "").strip().lower()
        source_requested_action = (source_analysis.requested_action or "").strip().lower()

    for candidate in queryset:
        score = 0
        reasons = []

        candidate_sender = normalize_sender(candidate.sender)

        # --- direct sender match ---
        if source_sender and candidate_sender and source_sender == candidate_sender:
            score += 50
            reasons.append("Same sender")

        candidate_analysis = getattr(candidate, "ai_analysis", None)

        candidate_urls = set()
        candidate_domains = set()
        candidate_emails = set()
        candidate_phone_numbers = set()
        candidate_brand = ""
        candidate_scam_category = ""
        candidate_requested_action = ""

        if candidate_analysis:
            candidate_urls = normalized_list(candidate_analysis.detected_urls)
            candidate_domains = normalized_list(candidate_analysis.detected_domains)
            candidate_emails = normalized_list(candidate_analysis.detected_emails)
            candidate_phone_numbers = normalized_list(candidate_analysis.detected_phone_numbers)
            candidate_brand = (candidate_analysis.impersonated_brand or "").strip().lower()
            candidate_scam_category = (candidate_analysis.scam_category or "").strip().lower()
            candidate_requested_action = (candidate_analysis.requested_action or "").strip().lower()

        # --- cross-check sender field against extracted indicators ---
        if source_sender:
            if source_sender in candidate_emails:
                score += 40
                reasons.append("Sender matches extracted email")
            if source_sender in candidate_domains:
                score += 30
                reasons.append("Sender matches extracted domain")
            if source_sender in candidate_phone_numbers:
                score += 40
                reasons.append("Sender matches extracted phone number")

        if candidate_sender:
            if candidate_sender in source_emails:
                score += 40
                reasons.append("Extracted email matches sender")
            if candidate_sender in source_domains:
                score += 30
                reasons.append("Extracted domain matches sender")
            if candidate_sender in source_phone_numbers:
                score += 40
                reasons.append("Extracted phone number matches sender")

        # --- exact extracted indicator matches ---
        shared_urls = source_urls.intersection(candidate_urls)
        if shared_urls:
            score += 45
            reasons.append("Same suspicious URL")

        shared_domains = source_domains.intersection(candidate_domains)
        if shared_domains:
            score += 35
            reasons.append("Same domain")

        shared_emails = source_emails.intersection(candidate_emails)
        if shared_emails:
            score += 35
            reasons.append("Same email address")

        shared_phone_numbers = source_phone_numbers.intersection(candidate_phone_numbers)
        if shared_phone_numbers:
            score += 40
            reasons.append("Same phone number")

        if source_brand and candidate_brand and source_brand == candidate_brand:
            score += 20
            reasons.append(f"Same impersonated brand: {candidate_analysis.impersonated_brand}")

        if source_scam_category and candidate_scam_category and source_scam_category == candidate_scam_category:
            score += 15
            reasons.append(f"Same scam category: {candidate_analysis.scam_category}")

        if (
            source_requested_action and
            candidate_requested_action and
            source_requested_action == candidate_requested_action
        ):
            score += 10
            reasons.append(f"Same requested action: {candidate_analysis.requested_action}")

        # --- content similarity fallback ---
        candidate_content_words = clean_word_set(candidate.message_content)
        overlap = source_content_words.intersection(candidate_content_words)

        if overlap:
            overlap_count = len(overlap)

            if overlap_count >= 2:
                score += overlap_count * 2

                if overlap_count >= 5:
                    reasons.append("Very similar wording")
                else:
                    reasons.append("Some similar wording")

        if score > 10:
            unique_reasons = []
            seen = set()
            for reason in reasons:
                if reason not in seen:
                    unique_reasons.append(reason)
                    seen.add(reason)

            results.append({
                "message": candidate,
                "score": score,
                "reasons": unique_reasons,
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:limit]