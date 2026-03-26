import json

from django.conf import settings
from google import genai

from analyzer.models import AIAnalysis


def analyze_message(message):
    """
    Uses the Gemini API to analyze a submitted message and return
    structured phishing-analysis data.
    """

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

    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in the environment.")

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
    )

    response_text = response.text.strip()
    analysis_data = json.loads(response_text)

    return {
        "verdict": analysis_data["verdict"],
        "confidence_score": int(analysis_data["confidence_score"]),
        "summary": analysis_data["summary"],
        "red_flags": analysis_data["red_flags"],
        "recommended_action": analysis_data["recommended_action"],
        "model_name": "gemini-3-flash-preview",
        "analysis_version": "gemini_v1",
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