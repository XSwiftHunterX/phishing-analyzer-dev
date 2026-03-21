from analyzer.models import AIAnalysis


def analyze_message(message):
    """
    Takes a Message instance and returns structured AI analysis data.
    Placeholder heuristic implementation with stronger logic.
    """

    content = (message.message_content or "").strip()
    content_lower = content.lower()

    sender = (message.sender or "").strip()
    sender_lower = sender.lower()

    additional_details = (message.additional_details or "").strip()
    details_lower = additional_details.lower()

    classification = (message.classification or "").strip()
    suspected_risk = (message.suspected_risk or "").strip()
    message_type = (message.message_type or "").strip()

    red_flags = []
    score = 0

    phishing_keywords = [
        "verify your account", "confirm your account", "login immediately",
        "click here", "reset your password", "password expired",
        "security alert", "suspended", "locked", "unauthorized login",
        "confirm your identity", "update your information",
        "bank", "ssn", "social security", "gift card", "wire transfer",
        "payment failed", "invoice", "urgent action required",
    ]

    urgency_keywords = [
        "urgent", "immediately", "asap", "within 24 hours",
        "act now", "final warning", "limited time", "expires today",
    ]

    credential_keywords = [
        "password", "login", "username", "account", "verify", "identity"
    ]

    money_keywords = [
        "payment", "invoice", "bank", "refund", "gift card",
        "transfer", "deposit", "crypto", "bitcoin"
    ]

    threat_keywords = [
        "suspended", "terminated", "locked", "penalty",
        "legal action", "arrest", "fine"
    ]

    suspicious_tlds = [
        ".ru", ".cn", ".tk", ".top", ".xyz", ".click", ".work", ".zip"
    ]

    # --- content keyword checks ---
    for keyword in phishing_keywords:
        if keyword in content_lower:
            red_flags.append(f"Contains suspicious phrase: '{keyword}'")
            score += 10

    for keyword in urgency_keywords:
        if keyword in content_lower:
            red_flags.append(f"Uses urgency tactic: '{keyword}'")
            score += 6

    # --- category signals ---
    if any(word in content_lower for word in credential_keywords):
        red_flags.append("Requests account or login-related action")
        score += 12

    if any(word in content_lower for word in money_keywords):
        red_flags.append("Mentions money, billing, or payment-related pressure")
        score += 10

    if any(word in content_lower for word in threat_keywords):
        red_flags.append("Uses threat or punishment language")
        score += 10

    # --- sender checks ---
    if "@" in sender_lower:
        if not sender_lower.endswith((".com", ".org", ".edu", ".gov", ".net")):
            red_flags.append("Sender email domain looks unusual")
            score += 8

        for tld in suspicious_tlds:
            if sender_lower.endswith(tld):
                red_flags.append(f"Sender uses a suspicious top-level domain ({tld})")
                score += 12

    if sender and len(sender) < 3:
        red_flags.append("Sender information is unusually short or unclear")
        score += 4

    # --- links and formatting clues ---
    if "http://" in content_lower:
        red_flags.append("Contains a non-secure link (http)")
        score += 12

    if "https://" in content_lower or "www." in content_lower:
        red_flags.append("Contains a link, which should be verified carefully")
        score += 6

    if content.count("!") >= 3:
        red_flags.append("Excessive punctuation may be used to create pressure")
        score += 4

    # --- user-provided context signals ---
    if classification:
        if classification.lower() in ["phishing", "scam"]:
            red_flags.append("User classified this submission as phishing/scam related")
            score += 8

    if suspected_risk:
        if suspected_risk.lower() in ["high", "critical"]:
            red_flags.append("User marked the suspected risk as high")
            score += 8
        elif suspected_risk.lower() == "medium":
            score += 4

    if additional_details:
        if "felt suspicious" in details_lower or "seemed fake" in details_lower:
            red_flags.append("User noted that the message felt suspicious")
            score += 5

    # --- message type signal ---
    if message_type.lower() == "sms":
        if any(word in content_lower for word in ["click", "login", "verify", "bank"]):
            red_flags.append("SMS messages requesting action are a common phishing pattern")
            score += 6

    # --- de-duplicate flags while preserving order ---
    seen = set()
    unique_red_flags = []
    for flag in red_flags:
        if flag not in seen:
            unique_red_flags.append(flag)
            seen.add(flag)

    red_flags = unique_red_flags

    # --- determine verdict ---
    if score >= 45:
        verdict = "likely_phishing"
    elif score >= 22:
        verdict = "suspicious"
    elif score >= 10:
        verdict = "unclear"
    else:
        verdict = "likely_legitimate"

    confidence_score = max(5, min(score, 95))

    # --- summary ---
    if verdict == "likely_phishing":
        summary = (
            "This submission shows several common phishing indicators, such as urgency, "
            "requests for sensitive action, suspicious sender characteristics, or scam-related language."
        )
        recommended_action = (
            "Do not click links, download attachments, or reply directly. "
            "Verify the sender through an official website or trusted contact method."
        )
    elif verdict == "suspicious":
        summary = (
            "This submission contains some warning signs that are commonly associated with phishing or scams, "
            "but the evidence is not overwhelming."
        )
        recommended_action = (
            "Use caution. Verify any links, requests, or sender details independently before taking action."
        )
    elif verdict == "unclear":
        summary = (
            "This submission has limited warning signs. It is not clearly malicious, "
            "but there is not enough evidence to confidently treat it as safe."
        )
        recommended_action = (
            "Be cautious and confirm the legitimacy of the sender before responding or clicking anything."
        )
    else:
        summary = (
            "This submission does not currently show many strong phishing indicators based on the available text."
        )
        recommended_action = (
            "Still verify unexpected requests independently, especially if the message asks for personal, account, or payment information."
        )

    return {
        "verdict": verdict,
        "confidence_score": confidence_score,
        "summary": summary,
        "red_flags": red_flags,
        "recommended_action": recommended_action,
        "model_name": "heuristic_v2",
        "analysis_version": "2.0",
        "raw_response": {
            "score": score,
            "message_type": message_type,
            "classification": classification,
            "suspected_risk": suspected_risk,
        }
    }


def save_analysis_result(message, analysis_data):
    """
    Saves analysis results to the database.
    """

    AIAnalysis.objects.update_or_create(
        message=message,
        defaults={
            "verdict": analysis_data["verdict"],
            "confidence_score": analysis_data["confidence_score"],
            "summary": analysis_data["summary"],
            "red_flags": analysis_data["red_flags"],
            "recommended_action": analysis_data["recommended_action"],
            "model_name": analysis_data.get("model_name", ""),
            "analysis_version": analysis_data.get("analysis_version", ""),
            "raw_response": analysis_data.get("raw_response", {}),
        }
    )