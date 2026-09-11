"""Research tool calls may use explicitly configured DeepSeek backup routes."""
import logging

from ai_key_rotation import APIKeyPoolUnavailable, is_transient_llm_error
from ai_rate_limit import RateLimitedChatDeepSeek


def configured_research_models(primary):
    from ai_config import load_ai_config
    config = load_ai_config(include_key=False)
    return list(dict.fromkeys([primary, *(
        name for name in (config.get("model_api_keys") or {})
        if name.casefold().startswith("deepseek")
    )]))


class ResearchChatDeepSeek(RateLimitedChatDeepSeek):
    def _generate(self, *args, **kwargs):
        if self.streaming:
            return super()._generate(*args, **kwargs)
        models = configured_research_models(self.model_name)
        for index, name in enumerate(models):
            candidate = self.model_copy(update={"model_name": name})
            try:
                return RateLimitedChatDeepSeek._generate(candidate, *args, **kwargs)
            except Exception as exc:
                if index == len(models) - 1 or not (isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s", name, type(exc).__name__, models[index + 1])

    async def _agenerate(self, *args, **kwargs):
        if self.streaming:
            return await super()._agenerate(*args, **kwargs)
        models = configured_research_models(self.model_name)
        for index, name in enumerate(models):
            candidate = self.model_copy(update={"model_name": name})
            try:
                return await RateLimitedChatDeepSeek._agenerate(candidate, *args, **kwargs)
            except Exception as exc:
                if index == len(models) - 1 or not (isinstance(exc, APIKeyPoolUnavailable) or is_transient_llm_error(exc)):
                    raise
                logging.warning("研究模型 %s 暂不可用（%s），使用已配置备用模型 %s", name, type(exc).__name__, models[index + 1])
