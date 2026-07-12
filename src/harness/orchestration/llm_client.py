"""LLM client for streaming completions via litellm."""

from typing import AsyncIterator
import litellm
import os

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
        # if not self.settings.api_key and not self.settings.auth_token:
        #     raise LLMConfigError("API key and auth_token not configured")
        if not self.settings.model and not model:
            raise LLMConfigError("Model not configured")
        try:
            active_model = model or self.settings.model


            # Build kwargs, include auth_token if present
            kwargs = {
                "model": f"openai/{active_model}",
                "api_base": self.settings.api_base,
                "api_key": self.settings.api_key or "none",
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "extra_headers": {"Authorization": f"Bearer {self.settings.auth_token}"} if self.settings.auth_token else None,
                "timeout": 30,
            }

            

            response = await litellm.acompletion(**kwargs)

            chunk_count = 0
            async for chunk in response:
                chunk_count += 1

                # Extract content, handle different chunk formats
                content = None
                if hasattr(chunk, 'choices') and chunk.choices and len(chunk.choices) > 0:
                    if hasattr(chunk.choices[0], 'delta'):
                        content = chunk.choices[0].delta.content

                if content:
                    yield content
        except Exception as LLM_EXC:
            raise LLMConfigError(f"LLM streaming error: {str(LLM_EXC)}") from LLM_EXC