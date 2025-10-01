#!/usr/bin/env python3
"""
Test script for the user profile MCP server.

This demonstrates how to use the get_user_profile tool to retrieve
user information through the MCP server interface.
"""

import asyncio

from pepper.constants import PEPPER_DIR
from pepper.llm_client.model import ToolCall
from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager


async def test_user_profile_tool():
    """Test the get_user_profile tool"""

    # Load the tools configuration
    # You can use either tools.yaml or tools_with_worker.yaml
    tool_config = load_tools_yaml(
        str(PEPPER_DIR / "agent" / "tool" / "scheduler_tools.yaml")
    )
    tool_resolved = build_stdio_params(tool_config)
    tool_manager = ToolManager(tool_resolved)

    tools = await tool_manager.list_openai_tools()

    # Find the get_user_profile tool
    profile_tool = None
    for tool in tools:
        if tool.get("function", {}).get("name") == "user-profile__get_user_profile":
            profile_tool = tool
            break

    if profile_tool:
        print("Found get_user_profile tool:")
        print(f"Description: {profile_tool['function']['description']}")
        print("\nCalling get_user_profile...")

        tool_call = ToolCall(
            id="test_call_1", name="user-profile__get_user_profile", arguments="{}"
        )

        try:
            result = await tool_manager.call_openai_tool(tool_call)

            # Extract the profile data from the result
            if result:
                profile_msg = result.result
                print("\nUser Profile Retrieved:")
                print("-" * 50)

                print(profile_msg)

        except Exception as e:
            print(f"Error calling tool: {e}")
    else:
        print("get_user_profile tool not found!")
        print("\nAvailable tools:")
        for tool in tools:
            print(f"  - {tool.get('function', {}).get('name')}")


async def main():
    """Main function"""
    print("User Profile MCP Server Test")
    print("=" * 60)

    await test_user_profile_tool()


if __name__ == "__main__":
    asyncio.run(main())
