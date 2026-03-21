from analyzer.models import AIAnalysis

def analyze_message(message):
    """
    Takes a Message instance and returns structured AI analysis data.
    This is a placeholder implementation for now.
    """

    content = (message.message_content or "").lower()
    sender = (message.sender or "").lower()

    red_flags = []
    verdict = "unclear"
    confidence = 50
    summary = "No strong indicators detected."
    recommended_action = "Use caution and verify the sender."

    # --- VERY SIMPLE HEURISTICS (TEMPORARY) ---
    suspicious_keywords = [
        "urgent", "verify your account", "login", "click here",
        "password", "bank", "ssn", "security alert"
    ]

    for keyword in suspicious_keywords:
        if keyword in content:
            red_flags.append(f"Contains suspicious phrase: '{keyword}'")

    if "@" in sender and not sender.endswith((".com", ".org", ".edu")):
        red_flags.append("Sender email domain looks unusual")

    if red_flags:
        verdict = "likely_phishing"
        confidence = min(70 + len(red_flags) * 5, 95)
        summary = "This message shows common phishing characteristics."

    return {
        "verdict": verdict,
        "confidence_score": confidence,
        "summary": summary,
        "red_flags": red_flags,
        "recommended_action": recommended_action,
        "model_name": "heuristic_v1",
        "analysis_version": "1.0",
        "raw_response": {}
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