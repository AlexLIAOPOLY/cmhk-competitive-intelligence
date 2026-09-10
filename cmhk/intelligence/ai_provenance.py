"""AI prose admission: evidence checks cannot turn templates into model output."""

AI_ONLY_POLICY = "model_generated_only_v1"


def model_generated_only(payload: dict) -> bool:
    if payload.get("generation_policy") != AI_ONLY_POLICY:
        return False
    if payload.get("fallback_used") or payload.get("discovery_fallback_used"):
        return False
    for key in ("model", "discovery_model"):
        model = str(payload.get(key) or "").lower()
        if not model or any(word in model for word in ("fallback", "deterministic", "evidence-rule")):
            return False

    def has_rule(value):
        if isinstance(value, dict):
            return value.get("origin") in {"evidence_rule", "deterministic", "rule"} or any(
                has_rule(item) for item in value.values()
            )
        return isinstance(value, list) and any(has_rule(item) for item in value)

    return bool(payload.get("summaries") and payload.get("discoveries") and not has_rule(payload))
