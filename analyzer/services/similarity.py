from django.db.models import Q
from analyzer.models import Message


def find_similar_messages(message, limit=5):
    """
    Finds messages similar to the given message based on:
    - same sender
    - overlapping keywords in content
    """

    queryset = Message.objects.filter(
        is_removed=False,
        moderation_status="approved"
    ).exclude(id=message.id)

    results = []

    content_words = set((message.message_content or "").lower().split())
    content_words = {word for word in content_words if len(word) > 4}

    for candidate in queryset:
        score = 0
        reasons = []

        # --- sender match ---
        if message.sender and candidate.sender:
            if message.sender.lower() == candidate.sender.lower():
                score += 50
                reasons.append("Same sender")

        # --- content similarity ---
        candidate_words = set((candidate.message_content or "").lower().split())
        overlap = content_words.intersection(candidate_words)

        if overlap:
            overlap_count = len(overlap)
            score += overlap_count * 2

            if overlap_count >= 5:
                reasons.append("Very similar wording")
            elif overlap_count >= 2:
                reasons.append("Some similar wording")

        if score > 0:
            results.append({
                "message": candidate,
                "score": score,
                "reasons": reasons
            })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:limit]