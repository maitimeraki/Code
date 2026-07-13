"""LLM client for streaming completions via litellm."""

import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Union
import litellm
import os

from harness.config import LLMSettings


class LLMConfigError(Exception):
    """LLM configuration error."""
    pass


@dataclass
class TextDelta:
    """Text content streamed from the model."""
    content: str


@dataclass
class ToolCallRequest:
    """A tool call from the model (fully accumulated and parsed)."""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolCallsReady:
    """Signal that tool calls have been fully accumulated and parsed."""
    tool_calls: list[ToolCallRequest]


@dataclass
class StreamDone:
    """Signal that the stream has completed."""
    finish_reason: str


StreamEvent = Union[TextDelta, ToolCallsReady, StreamDone]


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

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        fallback_models: Optional[list[str]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion with tool-calling support and delta accumulation.

        Args:
            messages: Conversation messages including system/user/assistant/tool roles.
            tools: Tool definitions in OpenAI/litellm format (from definitions.get_tools_payload).
            model: Model to use (overrides settings).
            fallback_models: List of models to try if the first fails before any text is yielded.

        Yields:
            StreamEvent: One of TextDelta, ToolCallsReady, or StreamDone.
        """
        active_model = model or self.settings.model
        models_to_try = [active_model] + (fallback_models or [])

        for attempt, try_model in enumerate(models_to_try):
            text_started = False
            try:
                kwargs = {
                    "model": f"openai/{try_model}",
                    "api_base": self.settings.api_base,
                    "api_key": self.settings.api_key or "none",
                    "messages": messages,
                    "stream": True,
                    "tools": tools,
                    "tool_choice": "auto" if tools else None,
                    "extra_headers": {"Authorization": f"Bearer {self.settings.auth_token}"}
                    if self.settings.auth_token
                    else None,
                    "timeout": 30,
                }

                response = await litellm.acompletion(**kwargs)

                # Accumulator for tool calls across chunks
                accumulating: dict[int, dict] = {}

                async for chunk in response:
                    if not hasattr(chunk, "choices") or not chunk.choices:
                        continue

                    choice = chunk.choices[0]

                    # Handle text content
                    if hasattr(choice, "delta") and hasattr(choice.delta, "content"):
                        content = choice.delta.content
                        if content:
                            text_started = True
                            yield TextDelta(content=content)

                    # Handle tool calls
                    if hasattr(choice, "delta") and hasattr(choice.delta, "tool_calls"):
                        for tc_delta in choice.delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in accumulating:
                                accumulating[idx] = {"arguments": ""}

                            # Set id/name if present (only on first fragment)
                            if hasattr(tc_delta, "id") and tc_delta.id:
                                accumulating[idx]["id"] = tc_delta.id
                            if hasattr(tc_delta, "function") and hasattr(tc_delta.function, "name"):
                                accumulating[idx]["name"] = tc_delta.function.name

                            # Accumulate arguments string (partial JSON across chunks)
                            if (
                                hasattr(tc_delta, "function")
                                and hasattr(tc_delta.function, "arguments")
                                and tc_delta.function.arguments
                            ):
                                accumulating[idx]["arguments"] += tc_delta.function.arguments

                    # Check for finish reason
                    if hasattr(choice, "finish_reason") and choice.finish_reason:
                        finish_reason = choice.finish_reason

                        # At stream end, parse accumulated tool calls
                        if accumulating:
                            tool_calls_ready = []
                            for idx in sorted(accumulating.keys()):
                                entry = accumulating[idx]
                                try:
                                    args_dict = json.loads(entry["arguments"])
                                except json.JSONDecodeError as e:
                                    # Tier 0 fallback: malformed JSON (possibly truncated)
                                    # Convert to a tool error message instead of crashing
                                    args_dict = {"_error": f"Malformed JSON in arguments: {str(e)}"}

                                tool_calls_ready.append(
                                    ToolCallRequest(
                                        id=entry.get("id", ""),
                                        name=entry.get("name", ""),
                                        arguments=args_dict,
                                    )
                                )
                            yield ToolCallsReady(tool_calls=tool_calls_ready)

                        yield StreamDone(finish_reason=finish_reason)
                        return

            except Exception as e:
                # If text hasn't started and we have fallback models, try the next one
                if not text_started and attempt < len(models_to_try) - 1:
                    continue
                # Otherwise, surface the error
                raise LLMConfigError(f"LLM streaming error: {str(e)}") from e

        # Exhausted all models without success
        raise LLMConfigError("All fallback models exhausted")