"""LLM client for streaming completions via litellm."""

from typing import AsyncIterator
import litellm

from harness.config import LLMSettings


class LLMConfigError(Exception):
    """LLM configuration error."""
    pass


class LLMClient:
    """Client for calling LLM providers via litellm with streaming support."""

    def __init__(self, settings: LLMSettings | None = None):
        self.settings = settings if settings is not None else LLMSettings.from_env()

    async def stream(self, prompt: str, model: str | None = None) -> AsyncIterator[str]:
        """Stream completion using configured model and provider (or override model)."""
        if not self.settings.api_key:
            raise LLMConfigError("API key not configured")
        if not self.settings.model and not model:
            raise LLMConfigError("Model not configured")

        active_model = model or self.settings.model
        response = await litellm.acompletion(
            model=active_model,
            api_base=self.settings.api_base,
            api_key=self.settings.api_key,
            messages=[{"role": "user", "content": prompt}],
            extra_headers={
            "Authorization": f"Bearer {self.settings.auth_token}" # Your gateway's token
            },
            stream=True,
        )

        async for chunk in response:
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content
