import json
import os
import re
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from ai_config import load_ai_config

_llm = None


def parse_verification_response(content: str) -> dict:
    content = (content or "").strip()
    if content.startswith("```json"):
        content = content[7:-3].strip()
    elif content.startswith("```"):
        content = content[3:-3].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        partial = parse_partial_verification_response(content)
        if partial:
            return partial
        raise ValueError(f"no JSON object in verification response: {content[:300]}")
    return json.loads(match.group(0))


def parse_partial_verification_response(content: str) -> dict:
    score_match = re.search(r'"?confidence_score"?\s*:\s*([01](?:\.\d+)?)', content)
    reason_match = re.search(r'"?verification_reason"?\s*:\s*"?(.*)', content, re.S)
    if not score_match and not reason_match:
        return {}
    reason = ""
    if reason_match:
        reason = reason_match.group(1).strip()
        reason = re.split(r'"\s*,?\s*"|\n\s*}', reason, maxsplit=1)[0]
        reason = reason.strip().strip('"').strip()
    return {
        "confidence_score": float(score_match.group(1)) if score_match else 0.5,
        "verification_reason": reason[:500] or "Partial verification response parsed.",
        "verification_status": "partial_response",
    }


def normalize_verification_result(result: dict) -> dict:
    try:
        score = float(result.get("confidence_score", 0.5))
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))
    reason = str(result.get("verification_reason", "No reason provided."))
    normalized = {
        "confidence_score": score,
        "verification_reason": reason,
    }
    if result.get("verification_status"):
        normalized["verification_status"] = str(result.get("verification_status"))
    return normalized

def get_verification_llm():
    global _llm
    if _llm is None:
        config = load_ai_config()
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        model_name = config.get("model", "deepseek-v4")
            
        _llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            api_base=base_url,
            extra_body=dict(config.get("extra_parameters") or {}),
            max_retries=3,
        )
    return _llm

def verify_extraction(raw_text: str, extracted_data: dict) -> dict:
    if not extracted_data:
        return {"confidence_score": 0.0, "verification_reason": "No data extracted."}
        
    llm = get_verification_llm()
    truncated_text = raw_text[:8000] if raw_text else ""
    
    prompt = f"""You are a Data Verification Agent.
Your task is to verify if the 'Extracted Data' accurately reflects the 'Source Text'.
Extracted Data:
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Source Text:
{truncated_text}

Provide your response in raw JSON format with NO markdown wrapping. It must contain exactly these two keys:
{{
  "confidence_score": <float between 0.0 and 1.0>,
  "verification_reason": "<one short sentence, max 80 characters>"
}}
"""
    try:
        response = llm.invoke([SystemMessage(content="You are a JSON-only response bot. Only output valid JSON without any markdown tags like ```json."), HumanMessage(content=prompt)])
        result = parse_verification_response(str(response.content))
        return normalize_verification_result(result)
    except Exception as e:
        print(f"Verification LLM failed: {e}")
        return {
            "confidence_score": 0.5,
            "verification_reason": f"Verification unavailable; crawl result not downgraded: {e}",
            "verification_status": "unavailable",
        }
