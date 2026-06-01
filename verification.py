import json
import os
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from ai_config import load_ai_config

_llm = None

def get_verification_llm():
    global _llm
    if _llm is None:
        config = load_ai_config()
        api_key = config.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
        base_url = config.get("base_url", "") or os.environ.get("OPENAI_API_BASE", "")
        model_name = config.get("model", "deepseek-chat")
        
        if "reasoner" in model_name:
            model_name = "deepseek-chat"
            
        _llm = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            api_base=base_url,
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
  "verification_reason": "<brief explanation of the score>"
}}
"""
    try:
        response = llm.invoke([SystemMessage(content="You are a JSON-only response bot. Only output valid JSON without any markdown tags like ```json."), HumanMessage(content=prompt)])
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        
        result = json.loads(content)
        return {
            "confidence_score": float(result.get("confidence_score", 0.5)),
            "verification_reason": str(result.get("verification_reason", "No reason provided."))
        }
    except Exception as e:
        print(f"Verification LLM failed: {e}")
        return {
            "confidence_score": 0.0,
            "verification_reason": f"Verification failed: {e}"
        }
