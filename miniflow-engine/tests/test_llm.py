"""Tests for llm.py — provider catalog, model-string builder, chat() shape."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_list_providers_shape():
    import llm
    providers = llm.list_providers()
    assert isinstance(providers, list)
    ids = [p["id"] for p in providers]
    for required in ("openai", "anthropic", "gemini", "ollama"):
        assert required in ids, f"Missing provider: {required}"
    for p in providers:
        # Must be JSON-serializable primitives
        assert set(p.keys()) >= {
            "id", "display_name", "requires_key", "supports_tools",
            "default_model", "suggested_models",
        }
        assert isinstance(p["suggested_models"], list)


def test_build_model_string_openai_passthrough():
    import llm
    assert llm.build_model_string("openai", "gpt-4o") == "gpt-4o"


def test_build_model_string_anthropic_prefixed():
    import llm
    assert llm.build_model_string("anthropic", "claude-3-5-sonnet-20241022") \
        == "anthropic/claude-3-5-sonnet-20241022"


def test_build_model_string_idempotent():
    """Calling twice (or with an already-prefixed model) shouldn't double-prefix."""
    import llm
    once = llm.build_model_string("gemini", "gemini-1.5-pro")
    twice = llm.build_model_string("gemini", once)
    assert once == twice == "gemini/gemini-1.5-pro"


def test_build_model_string_unknown_provider_raises():
    import llm
    with pytest.raises(ValueError, match="Unknown provider"):
        llm.build_model_string("does-not-exist", "foo")


def test_ollama_tool_capability_gate():
    import llm
    assert llm.ollama_model_is_tool_capable("llama3.1:8b-instruct-q4_K_M")
    assert llm.ollama_model_is_tool_capable("qwen2.5:14b-instruct")
    assert not llm.ollama_model_is_tool_capable("codellama:7b")
    assert not llm.ollama_model_is_tool_capable("phi-3:mini")


@pytest.mark.asyncio
async def test_chat_normalizes_response(monkeypatch):
    """llm.chat() must return an LLMResponse dataclass, never litellm's raw shape."""
    import llm

    # Fake litellm response matching the OpenAI ChatCompletion surface
    fake_tool_call = MagicMock()
    fake_tool_call.id = "call_abc"
    fake_tool_call.function.name = "open_application"
    fake_tool_call.function.arguments = '{"name": "Finder"}'

    fake_msg = MagicMock()
    fake_msg.content = None
    fake_msg.tool_calls = [fake_tool_call]

    fake_choice = MagicMock()
    fake_choice.message = fake_msg

    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]

    async def fake_acompletion(**kwargs):
        assert kwargs["model"] == "anthropic/claude-3-5-sonnet-20241022"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["tool_choice"] == "auto"
        return fake_resp

    import litellm
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = await llm.chat(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "open_application"}}],
        api_key="sk-test",
    )
    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc"
    assert result.tool_calls[0].name == "open_application"
    assert result.tool_calls[0].arguments_json == '{"name": "Finder"}'


@pytest.mark.asyncio
async def test_chat_omits_tools_when_provider_unsupported(monkeypatch):
    """If we ever add a tool-less provider, chat() should omit tools even if passed."""
    import llm
    llm.PROVIDERS["noop"] = {
        "display_name": "NoOp", "litellm_prefix": "noop/",
        "requires_key": False, "supports_tools": False,
        "default_model": "m", "suggested_models": ["m"],
    }

    captured: dict = {}
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        m = MagicMock(); m.content = "hello"; m.tool_calls = None
        c = MagicMock(); c.message = m
        r = MagicMock(); r.choices = [c]
        return r

    import litellm
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    await llm.chat(
        provider="noop", model="m", messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "foo"}}],
    )
    assert "tools" not in captured, "tools should be omitted for non-tool providers"
    assert "tool_choice" not in captured
