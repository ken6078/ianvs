"""Deterministic OpenAI SDK adapter for opt-in LLM smoke tests.

The adapter replaces both the current client API and the legacy module-level
chat API.  It intentionally implements only text generation; no request can
reach an OpenAI-compatible service while the mock runtime is enabled.
"""

import json
import threading
from collections.abc import Mapping


class _MockObject(dict):
    """Small attribute-accessible mapping resembling OpenAI response models."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    __setattr__ = dict.__setitem__

    def model_dump(self, **_kwargs):
        return _to_plain_dict(self)

    def dict(self, **_kwargs):
        return self.model_dump()

    def json(self, **kwargs):
        return json.dumps(self.model_dump(), **kwargs)


def _to_plain_dict(value):
    if isinstance(value, Mapping):
        return {key: _to_plain_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_dict(item) for item in value]
    return value


def _message_text(message):
    if isinstance(message, Mapping):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")

    # Multimodal-style content may contain several typed blocks.  Text blocks
    # are enough to make fixture matching useful without modelling the SDK.
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, Mapping):
                parts.append(str(part.get("text", part.get("content", ""))))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def _prompt_candidates(kwargs):
    messages = kwargs.get("messages")
    if isinstance(messages, (list, tuple)):
        parts = [_message_text(message) for message in messages]
        candidates = ["\n".join(parts)]
        if parts:
            candidates.append(parts[-1])
        return candidates

    value = kwargs.get("prompt", kwargs.get("input", ""))
    if isinstance(value, (list, tuple)):
        parts = [_message_text(item) for item in value]
        return ["\n".join(parts)] + ([parts[-1]] if parts else [])
    return [str(value)]


class _ResponseSelector:
    def __init__(self, responses):
        self._responses = responses
        self._response_index = 0
        self._lock = threading.Lock()

    def next(self, kwargs):
        prompt_responses = self._responses.get("prompt_responses", {})
        if isinstance(prompt_responses, Mapping):
            for prompt in _prompt_candidates(kwargs):
                if prompt in prompt_responses:
                    return str(prompt_responses[prompt])

        with self._lock:
            sequence = self._responses.get("sequence", [])
            if isinstance(sequence, (list, tuple)) and self._response_index < len(
                sequence
            ):
                response = sequence[self._response_index]
                self._response_index += 1
                return str(response)
        return str(self._responses.get("default", ""))


def _usage(kwargs, content):
    prompt = _prompt_candidates(kwargs)[0]
    prompt_tokens = len(prompt.split())
    completion_tokens = len(content.split())
    return _MockObject(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _chat_response(content, kwargs):
    return _MockObject(
        id="ianvs-mock-chat-completion",
        object="chat.completion",
        model=str(kwargs.get("model", "ianvs-mock")),
        choices=[
            _MockObject(
                index=0,
                finish_reason="stop",
                message=_MockObject(role="assistant", content=content),
                text=content,
            )
        ],
        usage=_usage(kwargs, content),
    )


def _completion_response(content, kwargs):
    return _MockObject(
        id="ianvs-mock-completion",
        object="text_completion",
        model=str(kwargs.get("model", "ianvs-mock")),
        choices=[_MockObject(index=0, finish_reason="stop", text=content)],
        usage=_usage(kwargs, content),
    )


def _response_api_response(content, kwargs):
    return _MockObject(
        id="ianvs-mock-response",
        object="response",
        model=str(kwargs.get("model", "ianvs-mock")),
        status="completed",
        output_text=content,
        output=[
            _MockObject(
                type="message",
                role="assistant",
                content=[_MockObject(type="output_text", text=content)],
            )
        ],
        usage=_usage(kwargs, content),
    )


class _SyncStream:
    def __init__(self, content, kwargs):
        self._chunks = iter(
            [
                _MockObject(
                    id="ianvs-mock-chat-completion",
                    object="chat.completion.chunk",
                    model=str(kwargs.get("model", "ianvs-mock")),
                    choices=[
                        _MockObject(
                            index=0,
                            finish_reason=None,
                            delta=_MockObject(role="assistant", content=content),
                        )
                    ],
                    usage=None,
                ),
                _MockObject(
                    id="ianvs-mock-chat-completion",
                    object="chat.completion.chunk",
                    model=str(kwargs.get("model", "ianvs-mock")),
                    choices=[],
                    usage=_usage(kwargs, content),
                ),
            ]
        )

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class _AsyncStream:
    def __init__(self, stream):
        self._stream = stream

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._stream)
        except StopIteration:
            raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class _ChatCompletions:
    def __init__(self, selector):
        self._selector = selector

    def create(self, *args, **kwargs):
        if args:
            raise TypeError("Mock chat completions accept keyword arguments only")
        content = self._selector.next(kwargs)
        if kwargs.get("stream"):
            return _SyncStream(content, kwargs)
        return _chat_response(content, kwargs)


class _Completions:
    def __init__(self, selector):
        self._selector = selector

    def create(self, *args, **kwargs):
        if args:
            raise TypeError("Mock completions accept keyword arguments only")
        content = self._selector.next(kwargs)
        return _completion_response(content, kwargs)


class _Responses:
    def __init__(self, selector):
        self._selector = selector

    def create(self, *args, **kwargs):
        if args:
            raise TypeError("Mock responses accept keyword arguments only")
        content = self._selector.next(kwargs)
        return _response_api_response(content, kwargs)


class _AsyncChatCompletions(_ChatCompletions):
    async def create(self, *args, **kwargs):
        result = super().create(*args, **kwargs)
        if isinstance(result, _SyncStream):
            return _AsyncStream(result)
        return result


class _AsyncCompletions(_Completions):
    async def create(self, *args, **kwargs):
        return super().create(*args, **kwargs)


class _AsyncResponses(_Responses):
    async def create(self, *args, **kwargs):
        return super().create(*args, **kwargs)


def _client(selector, asynchronous=False):
    client = _MockObject()
    chat_completions = (
        _AsyncChatCompletions(selector) if asynchronous else _ChatCompletions(selector)
    )
    client.chat = _MockObject(completions=chat_completions)
    client.completions = (
        _AsyncCompletions(selector) if asynchronous else _Completions(selector)
    )
    client.responses = (
        _AsyncResponses(selector) if asynchronous else _Responses(selector)
    )
    return client


def install(responses):
    """Replace OpenAI text-generation entry points with deterministic mocks."""
    if not isinstance(responses, Mapping):
        raise TypeError("OpenAI mock responses must be a mapping")

    import openai

    selector = _ResponseSelector(responses)

    class MockOpenAI:
        def __new__(cls, *_args, **_kwargs):
            return _client(selector)

    class MockAsyncOpenAI:
        def __new__(cls, *_args, **_kwargs):
            return _client(selector, asynchronous=True)

    # Current SDK entry points.
    openai.OpenAI = MockOpenAI
    openai.Client = MockOpenAI
    openai.AsyncOpenAI = MockAsyncOpenAI
    openai.AsyncClient = MockAsyncOpenAI
    openai.chat = _MockObject(completions=_ChatCompletions(selector))
    openai.completions = _Completions(selector)
    openai.responses = _Responses(selector)

    # Pre-1.0 SDK entry points, still used by some Ianvs examples.
    openai.ChatCompletion = _ChatCompletions(selector)
    openai.Completion = _Completions(selector)
