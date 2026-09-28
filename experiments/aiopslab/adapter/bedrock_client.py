"""Bedrock-safe OpenAI-compatible client for AIOpsLab baselines.

AIOpsLab's stock GenericOpenAIClient sends temperature AND top_p (plus frequency/presence
penalties). Anthropic Claude on Bedrock (via the litellm proxy) rejects temperature+top_p
together and does not support the penalties. This subclass sends temperature only, so the
baseline can run on claude-opus-4-6 (same model as Nous).
"""
from clients.utils.llm import GenericOpenAIClient


class BedrockSafeOpenAIClient(GenericOpenAIClient):
    def inference(self, payload):
        if self.cache is not None:
            cached = self.cache.get_from_cache(payload)
            if cached is not None:
                return cached
        resp = self.client.chat.completions.create(
            messages=payload,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.5,
            n=1,
            timeout=120,
        )
        return [c.message.content for c in resp.choices]
