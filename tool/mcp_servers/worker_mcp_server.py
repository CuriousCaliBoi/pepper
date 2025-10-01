from typing import Optional

from fastmcp import FastMCP

from pepper.agent.worker import WorkerAgent

mcp = FastMCP("worker-mcp-server")


@mcp.tool()
async def stateless_agent(request: str) -> str:
    """Execute a request using the worker agent with available tools.

    Don't use this tool for anything that requires context from previous requests. You should use the stateful agent instead.
    Use the tool if you want to perform a one-time task.
    When using this tool, provide all necessary information in the request.

    The stateless agent can:
    - Read files using the reading tool
    - Think step-by-step to complete complex tasks
    - Return a final answer when done

    Args:
        request: The task or request to be executed by the worker agent

    Returns:
        str: The final answer or result from the worker agent
    """
    try:
        # Create a new worker agent instance for each request
        agent = WorkerAgent()

        # Call the agent with the request and get the result
        result = await agent.call(request)

        return result
    except Exception as e:
        import traceback

        return f"[ERROR]: Worker agent failed to execute request: {str(e)} {traceback.format_exc()}"


@mcp.tool()
async def stateful_agent(request: str, agent_name: str) -> str:
    """Execute a request using a stateful agent with available tools.

    You should use this tool when your task requires context from previous requests.

    For example, you should use "Email agent" when you need to due with anything related to email.
    For example, you should use "Reminder agent" when you need to due with anything related to reminders.

    But for searching web or performing a one-time task, you should not use this tool. You should use the stateless agent instead.

    Args:
        request: The task or request to be executed by the stateful agent
        agent_name: The name of the agent to use

    The stateful agent can:
    - Send emails and manage calendar using Composio tools
    - Set reminders using Reminder tool
    - Think step-by-step to complete complex tasks
    - Return a final answer when done
    """
    try:
        # Create a new worker agent instance for each request
        agent = WorkerAgent()

        # Call the agent with the request and get the result
        result = await agent.call(request, agent_name)

        return result
    except Exception as e:
        import traceback

        return f"[ERROR]: Worker agent failed to execute request: {str(e)} {traceback.format_exc()}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
