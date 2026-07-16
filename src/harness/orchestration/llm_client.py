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

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        fallback_models: Optional[list[str]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion with optional tool-calling support.

        Yields text deltas for plain chat, tool calls when available, and a completion signal.

        Args:
            messages: Conversation messages including system/user/assistant/tool roles.
            tools: Optional tool definitions in OpenAI/litellm format (from definitions.get_tools_payload).
            model: Model to use (overrides settings).
            fallback_models: List of models to try if the first fails before any text is yielded.

        Yields:
            StreamEvent: One of TextDelta, ToolCallsReady, or StreamDone.
        """
        if not self.settings.model and not model:
            raise LLMConfigError("Model not configured")
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
                    "extra_headers": {"Authorization": f"Bearer {self.settings.auth_token}"}
                    if self.settings.auth_token
                    else None,
                    "timeout": 30,
                }
                # Only send tools/tool_choice when there are tools. Passing None
                # trips some OpenAI-compatible endpoints (they echo nulls back).
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = await litellm.acompletion(**kwargs)

                # Accumulator for tool calls across chunks
                accumulating: dict[int, dict] = {}

                # Handle non-streaming response (when stream=True is ignored by provider)
                if response is None:
                    raise LLMConfigError("LLM returned None response (stream not established)")

                # Debug response type - helps diagnose CustomStreamWrapper issues
                # response_type = type(response).__name__
                # response_module = type(response).__module__
                # if response_type == "CustomStreamWrapper":
                #     # For debugging CustomStreamWrapper iterator issues
                #     print(f"[DEBUG] CustomStreamWrapper: module={response_module}", flush=True)
                #     print(f"[DEBUG] Has __aiter__={hasattr(response, '__aiter__')}, __anext__={hasattr(response, '__anext__')}", flush=True)
                #     print(f"[DEBUG] Attrs: {[a for a in dir(response) if not a.startswith('_')]}", flush=True)

                # Check if response is NOT an async generator (could be dict or Response object)
                if not hasattr(response, "__aiter__"):
                    # Try to extract content from non-streaming response (dict or Response object)
                    try:
                        # Handle dict response
                        if isinstance(response, dict):
                            choices = response.get("choices", [])
                        # Handle litellm Response object with dict-like access
                        elif hasattr(response, "__getitem__"):
                            choices = response["choices"] if "choices" in response else []
                        # Handle Response object with .choices attribute
                        elif hasattr(response, "choices"):
                            choices = response.choices
                        else:
                            raise LLMConfigError(f"Unknown response format. Type: {type(response).__name__}")

                        choice = choices[0] if choices else None
                        if choice:
                            # Extract content from message or delta
                            content = None
                            if isinstance(choice, dict):
                                content = choice.get("message", {}).get("content") or choice.get("delta", {}).get("content")
                            elif hasattr(choice, "message"):
                                content = choice.message.content if hasattr(choice.message, "content") else None
                            elif hasattr(choice, "delta"):
                                content = choice.delta.content if hasattr(choice.delta, "content") else None

                            if content:
                                text_started = True
                                yield TextDelta(content=content)

                        # Get finish reason
                        finish_reason = "stop"
                        if choice:
                            if isinstance(choice, dict):
                                finish_reason = choice.get("finish_reason", "stop")
                            elif hasattr(choice, "finish_reason"):
                                finish_reason = choice.finish_reason

                        yield StreamDone(finish_reason=finish_reason)
                    except Exception as e:
                        raise LLMConfigError(f"Failed to parse non-streaming response: {str(e)}") from e
                    return

                try:
                    if not hasattr(response, "__aiter__"):
                        raise LLMConfigError(f"Response is not async iterable. Type: {type(response).__name__}")

                    async for chunk in response:
                        # Skip None chunks or chunks without choices
                        if chunk is None:
                            continue
                        if not "choices" in chunk or not chunk.choices:
                            continue

                        choice = chunk.choices[0]

                        # Handle text content
                        if choice.delta is not None and "content" in choice.delta:

                            content = choice.delta.content
                            if content:
                                text_started = True
                                yield TextDelta(content=content)

                        # Handle tool calls (streamed as fragments across chunks)
                        if choice.delta is not None and getattr(choice.delta, "tool_calls", None):
                            for tc_delta in choice.delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in accumulating:
                                    accumulating[idx] = {"arguments": ""}

                                # Set id/name if present (only on first fragment).
                                # Guard on truthiness: later fragments carry name=None,
                                # which would otherwise wipe the real name and produce
                                # a `"name": null` tool_call the API rejects (400).
                                if hasattr(tc_delta, "id") and tc_delta.id:
                                    accumulating[idx]["id"] = tc_delta.id
                                if (
                                    hasattr(tc_delta, "function")
                                    and getattr(tc_delta.function, "name", None)
                                ):
                                    accumulating[idx]["name"] = tc_delta.function.name

                                # Accumulate arguments string
                                # (partial JSON across chunks)
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
                except TypeError as e:
                    error_msg = str(e)
                    if "not iterable" in error_msg or "object is not async iterable" in error_msg:
                        # Try to extract chunks from wrapper attributes
                        try:
                            chunks = None
                            if hasattr(response, "completion_stream"):
                                chunks = response.completion_stream
                            elif hasattr(response, "chunks"):
                                chunks = response.chunks
                            elif hasattr(response, "fetch_sync_stream"):
                                chunks = response.fetch_sync_stream()
                            else:
                                chunks = list(response)

                            if not chunks:
                                raise LLMConfigError("No chunks extracted from response")

                            # Process chunks
                            for chunk in chunks:
                                choices = chunk.get("choices", []) if isinstance(chunk, dict) else getattr(chunk, "choices", [])
                                if not choices:
                                    continue

                                choice = choices[0]
                                delta = choice.get("delta", {}) if isinstance(choice, dict) else getattr(choice, "delta", {})

                                # Text content
                                content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
                                if content:
                                    text_started = True
                                    yield TextDelta(content=content)

                                # Finish reason
                                finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else getattr(choice, "finish_reason", None)
                                if finish_reason:
                                    if accumulating:
                                        tool_calls_ready = []
                                        for idx in sorted(accumulating.keys()):
                                            entry = accumulating[idx]
                                            try:
                                                args_dict = json.loads(entry["arguments"])
                                            except json.JSONDecodeError as je:
                                                args_dict = {"_error": str(je)}
                                            tool_calls_ready.append(ToolCallRequest(id=entry.get("id", ""), name=entry.get("name", ""), arguments=args_dict))
                                        yield ToolCallsReady(tool_calls=tool_calls_ready)
                                    yield StreamDone(finish_reason=finish_reason)
                                    return
                            return
                        except Exception:
                            pass

                        raise LLMConfigError(f"Response stream broken ({type(response).__name__}): {error_msg}") from e
                    raise

            except Exception as e:
                # If text hasn't started and we have fallback models, try the next one
                if not text_started and attempt < len(models_to_try) - 1:
                    continue
                # Otherwise, surface the error
                raise LLMConfigError(f"LLM streaming error: {str(e)}") from e

        # Exhausted all models without success
        raise LLMConfigError("All fallback models exhausted")