from django.utils import timezone

from ..models import Message, UserProfile


def flag_user_for_rate_limit(user):
    if not user or not user.is_authenticated:
        return

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.rate_limited_flag = True
    profile.flagged_at = timezone.now()

    existing_notes = (profile.admin_flag_notes or "").strip()
    new_note = "User hit submission rate limit."

    if new_note not in existing_notes:
        if existing_notes:
            profile.admin_flag_notes = existing_notes + "\n" + new_note
        else:
            profile.admin_flag_notes = new_note

    profile.save(update_fields=[
        "rate_limited_flag",
        "flagged_at",
        "admin_flag_notes",
    ])


def flag_user_for_exact_duplicate(message):
    if not message.user:
        return

    profile, _ = UserProfile.objects.get_or_create(user=message.user)
    profile.duplicate_abuse_flag = True
    profile.flagged_at = timezone.now()

    existing_notes = (profile.admin_flag_notes or "").strip()
    new_note = f"Exact duplicate submission detected on message #{message.id}."

    if new_note not in existing_notes:
        if existing_notes:
            profile.admin_flag_notes = existing_notes + "\n" + new_note
        else:
            profile.admin_flag_notes = new_note

    profile.save(update_fields=[
        "duplicate_abuse_flag",
        "flagged_at",
        "admin_flag_notes",
    ])