import json
import mimetypes

from django.conf import settings
from google import genai
from google.genai import types

from analyzer.models import AIAnalysis


PRIMARY_MODEL = "gemini-3.1-flash-lite-preview"
FALLBACK_MODEL = "gemini-3-flash-preview"


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "likely_phishing",
                "suspicious",
                "unclear",
                "likely_legitimate",
            ],
        },
        "confidence_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
        "summary": {"type": "string"},
        "red_flags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_action": {"type": "string"},

        "detected_urls": {
            "type": "array",
            "items": {"type": "string"},
        },
        "detected_domains": {
            "type": "array",
            "items": {"type": "string"},
        },
        "detected_emails": {
            "type": "array",
            "items": {"type": "string"},
        },
        "detected_phone_numbers": {
            "type": "array",
            "items": {"type": "string"},
        },

        "impersonated_brand": {"type": "string"},
        "scam_category": {"type": "string"},
        "requested_action": {"type": "string"},
    },
    "required": [
        "verdict",
        "confidence_score",
        "summary",
        "red_flags",
        "recommended_action",
        "detected_urls",
        "detected_domains",
        "detected_emails",
        "detected_phone_numbers",
        "impersonated_brand",
        "scam_category",
        "requested_action",
    ],
}


def _build_prompt(message):
    sender = (message.sender or "").strip()
    message_type = (message.message_type or "").strip()
    message_content = (message.message_content or "").strip()
    additional_details = (message.additional_details or "").strip()
    classification = (message.classification or "").strip()

    return f"""
You are analyzing a user-submitted suspicious message for a cybersecurity awareness website.

Your task:
1. Determine whether this message appears to be phishing, suspicious, unclear, or likely legitimate.
2. Explain the main warning signs.
3. Give practical user safety advice.
4. Extract structured scam indicators that can help match this report to similar reports.

Important instructions:
- Use BOTH the text fields and the screenshot if a screenshot is provided.
- Treat the screenshot as supporting evidence, not the only source of truth.
- Be cautious about overconfidence.
- Focus on phishing indicators such as impersonation, urgency, credential theft, suspicious links, payment requests, account threats, spoofed branding, or scam tactics.
- Only include information that is actually present or strongly supported.
- If a field is unknown, return:
  - empty array [] for list fields
  - empty string "" for text fields
- Return ONLY JSON matching the required schema.

Field guidance:
- detected_urls: full URLs found in the message or screenshot
- detected_domains: domains found in URLs, email addresses, or visible branding
- detected_emails: email addresses present in the message or screenshot
- detected_phone_numbers: phone numbers present in the message or screenshot
- impersonated_brand: company/brand/service being impersonated, if any
- scam_category: short category such as "account verification", "credential theft", "delivery scam", "fake invoice", "bank impersonation", "gift card scam", "crypto scam"
- requested_action: short phrase describing what the scam wants the user to do, such as "click a link", "call a number", "verify account", "send payment", "download attachment"

Submitted message data:
Sender: {sender}
Message type: {message_type}
Message content: {message_content}
Additional details: {additional_details}
User classification: {classification}
""".strip()


def _get_image_part(message):
    """
    Prefer the redacted screenshot if present.
    Otherwise use the original screenshot.
    Returns a Gemini image Part or None.
    """
    image_field = None

    if getattr(message, "redacted_screenshot", None):
        image_field = message.redacted_screenshot
    elif getattr(message, "screenshot", None):
        image_field = message.screenshot

    if not image_field:
        return None

    try:
        image_field.open("rb")
        image_bytes = image_field.read()
        image_field.close()

        if not image_bytes:
            return None

        mime_type, _ = mimetypes.guess_type(image_field.name)
        if not mime_type:
            mime_type = "image/png"

        return types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type,
        )
    except Exception:
        return None


def _normalize_analysis_data(analysis_data, model_name, response_text):
    verdict = analysis_data.get("verdict", "unclear")
    if verdict not in {
        "likely_phishing",
        "suspicious",
        "unclear",
        "likely_legitimate",
    }:
        verdict = "unclear"

    try:
        confidence_score = int(analysis_data.get("confidence_score", 50))
    except (TypeError, ValueError):
        confidence_score = 50

    confidence_score = max(0, min(confidence_score, 100))

    def clean_list(value):
        if not isinstance(value, list):
            return []
        cleaned = []
        seen = set()
        for item in value:
            text = str(item).strip()
            if text and text.lower() not in seen:
                cleaned.append(text)
                seen.add(text.lower())
        return cleaned

    red_flags = clean_list(analysis_data.get("red_flags", []))
    detected_urls = clean_list(analysis_data.get("detected_urls", []))
    detected_domains = clean_list(analysis_data.get("detected_domains", []))
    detected_emails = clean_list(analysis_data.get("detected_emails", []))
    detected_phone_numbers = clean_list(analysis_data.get("detected_phone_numbers", []))

    summary = str(analysis_data.get("summary", "")).strip()
    recommended_action = str(analysis_data.get("recommended_action", "")).strip()
    impersonated_brand = str(analysis_data.get("impersonated_brand", "")).strip()
    scam_category = str(analysis_data.get("scam_category", "")).strip()
    requested_action = str(analysis_data.get("requested_action", "")).strip()

    if not summary:
        summary = "The AI analysis did not return a usable summary."
    if not recommended_action:
        recommended_action = "Use caution and verify the sender independently."

    return {
        "verdict": verdict,
        "confidence_score": confidence_score,
        "summary": summary,
        "red_flags": red_flags,
        "recommended_action": recommended_action,

        "detected_urls": detected_urls,
        "detected_domains": detected_domains,
        "detected_emails": detected_emails,
        "detected_phone_numbers": detected_phone_numbers,
        "impersonated_brand": impersonated_brand,
        "scam_category": scam_category,
        "requested_action": requested_action,

        "model_name": model_name,
        "analysis_version": "gemini_multimodal_v2",
        "raw_response": {
            "response_text": response_text,
        },
    }


def _fallback_result(error_message):
    return {
        "verdict": "unclear",
        "confidence_score": 30,
        "summary": "AI analysis is temporarily unavailable.",
        "red_flags": [],
        "recommended_action": "Use caution and review the message manually.",

        "detected_urls": [],
        "detected_domains": [],
        "detected_emails": [],
        "detected_phone_numbers": [],
        "impersonated_brand": "",
        "scam_category": "",
        "requested_action": "",

        "model_name": "fallback",
        "analysis_version": "fallback",
        "raw_response": {"error": error_message},
    }


def analyze_message(message):
    """
    Uses Gemini to analyze a submitted message.
    Supports text-only and text+image analysis.
    """

    message_text = (message.message_content or "").strip()
    additional_details = (message.additional_details or "").strip()

    # Skip very low-information submissions.
    if len(message_text) < 15 and len(additional_details) < 15 and not message.screenshot:
        return {
            "verdict": "unclear",
            "confidence_score": 10,
            "summary": "Not enough information was provided to analyze this submission.",
            "red_flags": [],
            "recommended_action": "Provide more message content or a screenshot for a better analysis.",

            "detected_urls": [],
            "detected_domains": [],
            "detected_emails": [],
            "detected_phone_numbers": [],
            "impersonated_brand": "",
            "scam_category": "",
            "requested_action": "",

            "model_name": "skipped",
            "analysis_version": "skipped",
            "raw_response": {},
        }

    # Avoid duplicate analysis on the same saved message.
    try:
        existing = message.ai_analysis
        if existing:
            return {
                "verdict": existing.verdict,
                "confidence_score": existing.confidence_score,
                "summary": existing.summary,
                "red_flags": existing.red_flags,
                "recommended_action": existing.recommended_action,

                "detected_urls": existing.detected_urls,
                "detected_domains": existing.detected_domains,
                "detected_emails": existing.detected_emails,
                "detected_phone_numbers": existing.detected_phone_numbers,
                "impersonated_brand": existing.impersonated_brand,
                "scam_category": existing.scam_category,
                "requested_action": existing.requested_action,

                "model_name": existing.model_name,
                "analysis_version": existing.analysis_version,
                "raw_response": existing.raw_response,
            }
    except AIAnalysis.DoesNotExist:
        pass

    if not settings.GEMINI_API_KEY:
        return _fallback_result("GEMINI_API_KEY is not set.")

    prompt = _build_prompt(message)
    image_part = _get_image_part(message)

    contents = [prompt]
    if image_part:
        contents.append(image_part)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    last_error = "Unknown Gemini error"

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": ANALYSIS_SCHEMA,
                },
            )

            response_text = (response.text or "").strip()
            analysis_data = json.loads(response_text)

            return _normalize_analysis_data(
                analysis_data=analysis_data,
                model_name=model_name,
                response_text=response_text,
            )

        except Exception as e:
            last_error = f"{model_name}: {str(e)}"

    return _fallback_result(last_error)


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

            "detected_urls": analysis_data.get("detected_urls", []),
            "detected_domains": analysis_data.get("detected_domains", []),
            "detected_emails": analysis_data.get("detected_emails", []),
            "detected_phone_numbers": analysis_data.get("detected_phone_numbers", []),
            "impersonated_brand": analysis_data.get("impersonated_brand", ""),
            "scam_category": analysis_data.get("scam_category", ""),
            "requested_action": analysis_data.get("requested_action", ""),

            "model_name": analysis_data.get("model_name", ""),
            "analysis_version": analysis_data.get("analysis_version", ""),
            "raw_response": analysis_data.get("raw_response", {}),
        }
    )