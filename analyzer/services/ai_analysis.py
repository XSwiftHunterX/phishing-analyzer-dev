import json

from django.conf import settings
from google import genai

from analyzer.models import AIAnalysis


def analyze_message(message):
    """
    Uses Gemini API to analyze a submitted message.
    Includes safeguards to reduce unnecessary API calls.
    """

    # --- STEP 1: Skip low-value input ---
    if not message.message_content or len(message.message_content.strip()) < 15:
        return {
            "verdict": "unclear",
            "confidence_score": 10,
            "summary": "Not enough content to analyze.",
            "red_flags": [],
            "recommended_action": "Provide more message content for analysis.",
            "model_name": "skipped",
            "analysis_version": "skipped",
            "raw_response": {}
        }

    # --- STEP 2: Prevent duplicate analysis ---
    try:
        existing = message.ai_analysis
        if existing:
            return {
                "verdict": existing.verdict,
                "confidence_score": existing.confidence_score,
                "summary": existing.summary,
                "red_flags": existing.red_flags,
                "recommended_action": existing.recommended_action,
                "model_name": existing.model_name,
                "analysis_version": existing.analysis_version,
                "raw_response": existing.raw_response,
            }
    except AIAnalysis.DoesNotExist:
        pass

    # --- STEP 3: Prepare input data ---
    sender = (message.sender or "").strip()
    message_type = (message.message_type or "").strip()
    message_content = (message.message_content or "").strip()
    additional_details = (message.additional_details or "").strip()
    classification = (message.classification or "").strip()
    suspected_risk = (message.suspected_risk or "").strip()

    prompt = f"""
You are analyzing a user-submitted suspicious message for a cybersecurity awareness website.

Your job is to determine whether the message appears to be phishing, suspicious, unclear, or likely legitimate.

Return ONLY valid JSON with exactly these keys:
- verdict
- confidence_score
- summary
- red_flags
- recommended_action

Rules:
- verdict must be one of:
  - likely_phishing
  - suspicious
  - unclear
  - likely_legitimate
- confidence_score must be an integer from 0 to 100
- summary must be a short paragraph
- red_flags must be a JSON array of strings
- recommended_action must be a short paragraph
- Do not include markdown
- Do not include code fences
- Do not include any extra text outside the JSON

Submitted message data:
Sender: {sender}
Message type: {message_type}
Message content: {message_content}
Additional details: {additional_details}
User classification: {classification}
User suspected risk: {suspected_risk}
""".strip()

    # --- STEP 4: Ensure API key exists ---
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # --- STEP 5: Call Gemini safely ---
    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
    except Exception:
        # fallback if Lite isn't available or fails
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )

        response_text = response.text.strip()

        # Attempt to parse JSON
        analysis_data = json.loads(response_text)

    except Exception as e:
        return {
            "verdict": "unclear",
            "confidence_score": 30,
            "summary": "AI analysis temporarily unavailable.",
            "red_flags": [],
            "recommended_action": "Use caution and review the message manually.",
            "model_name": "fallback",
            "analysis_version": "fallback",
            "raw_response": {"error": str(e)}
        }

    # --- STEP 6: Return structured result ---
    return {
        "verdict": analysis_data.get("verdict", "unclear"),
        "confidence_score": int(analysis_data.get("confidence_score", 50)),
        "summary": analysis_data.get("summary", ""),
        "red_flags": analysis_data.get("red_flags", []),
        "recommended_action": analysis_data.get("recommended_action", ""),
        "model_name": "gemini-1.5-flash",
        "analysis_version": "gemini_v2",
        "raw_response": {
            "response_text": response_text
        },
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