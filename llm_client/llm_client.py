"""
Unified LLM client that routes to appropriate provider based on model name.
"""

import os
from typing import Any, Dict, List, Optional

from pepper.llm_client.model import AssistantMessage

# Simple model-to-provider mapping
MODEL_PROVIDERS = {
    # OpenAI models
    "gpt-4": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gpt-4-turbo": "openai",
    "gpt-3.5-turbo": "openai",
    # Claude models (via Bedrock)
    "claude-3-5-sonnet": "bedrock",
    "claude-3-5-haiku": "bedrock",
    "claude-3-opus": "bedrock",
    "claude-3-sonnet": "bedrock",
    "claude-3-haiku": "bedrock",
    # Claude models (direct API)
    "claude-3-5-sonnet-direct": "anthropic",
    "claude-3-5-haiku-direct": "anthropic",
    # Allow full model IDs as well
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0": "bedrock",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0": "bedrock",
}


def get_provider_for_model(model: str) -> str:
    """
    Determine which provider to use for a given model.

    You can also use environment variable LLM_PROVIDER to override:
    - Set LLM_PROVIDER=openai to use OpenAI for all models
    - Set LLM_PROVIDER=bedrock to use Bedrock for all models
    """
    # Check for override
    override_provider = os.environ.get("LLM_PROVIDER")
    if override_provider:
        return override_provider.lower()

    # Check the mapping
    provider = MODEL_PROVIDERS.get(model)
    if provider:
        return provider

    # Default fallback based on what's configured
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    elif os.environ.get("BEDROCK_API_KEY") or os.environ.get("AWS_API_KEY"):
        return "bedrock"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    raise ValueError(
        f"Cannot determine provider for model '{model}'. "
        f"Set LLM_PROVIDER env var or configure API keys."
    )


async def create_completion(
    messages: List[Dict[str, Any]],
    model: str,
    max_tokens: int = 1000,
    temperature: float = 0.7,
    tools: Optional[List[Dict[str, Any]]] = None,
    name: str = "llm_completion",
) -> AssistantMessage:
    """
    Unified function to create completions across different LLM providers.

    This function automatically routes to the appropriate provider based on:
    1. The LLM_PROVIDER environment variable (if set)
    2. The model name
    3. Available API keys

    Args:
        messages: List of messages in OpenAI format
        model: Model name (e.g., "gpt-4", "claude-3-5-sonnet")
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        tools: Optional list of tools in OpenAI format
        name: Name for logging/tracking

    Returns:
        AssistantMessage with the response

    Examples:
        # Use GPT-4
        response = await create_completion(messages, "gpt-4")

        # Use Claude via Bedrock
        response = await create_completion(messages, "claude-3-5-sonnet")

        # Force all models to use Bedrock by setting LLM_PROVIDER=bedrock
    """
    provider = get_provider_for_model(model)

    if provider == "openai":
        from pepper.llm_client.openai_client import call_openai_api as openai_completion

        return await openai_completion(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            name=name,
        )

    elif provider == "bedrock":
        from pepper.llm_client.bedrock_anthropic_client import (
            call_bedrock_api as bedrock_completion,
        )

        return await bedrock_completion(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            name=name,
        )

    elif provider == "anthropic":
        from pepper.llm_client.anthropic_client import (
            call_anthropic_api as anthropic_completion,
        )

        return await anthropic_completion(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            name=name,
        )

    else:
        raise ValueError(f"Unknown provider: {provider}")


# Optional: Helper function to check which providers are available
def get_available_providers() -> Dict[str, bool]:
    """
    Check which LLM providers are configured and available.

    Returns:
        Dict mapping provider names to availability status
    """
    return {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "bedrock": bool(
            os.environ.get("BEDROCK_API_KEY") or os.environ.get("AWS_API_KEY")
        ),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


# Optional: List available models based on configured providers
def list_available_models() -> List[str]:
    """
    List models available based on configured API keys.

    Returns:
        List of model names that can be used
    """
    available_providers = get_available_providers()
    models = []

    if available_providers["openai"]:
        models.extend(["gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])

    if available_providers["bedrock"]:
        models.extend(["claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus"])

    if available_providers["anthropic"]:
        models.extend(["claude-3-5-sonnet-direct", "claude-3-5-haiku-direct"])

    return models


if __name__ == "__main__":
    import asyncio

    async def test():
        # Test the unified client
        messages = [{"role": "user", "content": "Say hello!"}]

        # This will automatically route to the appropriate provider
        response = await create_completion(
            messages=messages,
            model="gpt-4",  # or "claude-3-5-sonnet" for Bedrock
            max_tokens=100,
            temperature=0.7,
        )

        print(f"Response: {response.content}")
        print(f"Available providers: {get_available_providers()}")
        print(f"Available models: {list_available_models()}")

    asyncio.run(test())
