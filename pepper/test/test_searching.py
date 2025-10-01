import asyncio
import os
import sys
from pathlib import Path

from pepper.tool.config_loader import build_stdio_params, load_tools_yaml
from pepper.tool.manager import ToolManager
from pepper.constants import PEPPER_DIR

async def main(entity: str | None = None):
    pepper_dir = PEPPER_DIR
    # Use the workflow tool config since it includes tool-searching
    servers = load_tools_yaml(str(pepper_dir / "agent" / "tool" / "workflow_tools.yaml"))
    resolved = build_stdio_params(servers)
    mgr = ToolManager(resolved)

    topic = entity or "OpenAI"

    # 1) No-API-key example: Wikipedia page content
    print(f"Calling tool-searching.wiki_get_page_content on: {topic}")
    wiki = await mgr.call(
        "tool-searching",
        "wiki_get_page_content",
        {"entity": topic, "first_sentences": 3},
    )
    print("Call result:", wiki)

    # 2) Optional: Google search (requires SERPER_API_KEY)
    if os.environ.get("SERPER_API_KEY"):
        print(f"Calling tool-searching.google_search on: {topic}")
        g = await mgr.call(
            "tool-searching",
            "google_search",
            {"q": topic, "num": 3},
        )
        print("Call result:", g)

    # 3) Optional: Scrape website (requires JINA_API_KEY or SERPER_API_KEY)
    if os.environ.get("JINA_API_KEY") or os.environ.get("SERPER_API_KEY"):
        url = "https://www.openai.com"
        print(f"Calling tool-searching.scrape_website on: {url}")
        s = await mgr.call("tool-searching", "scrape_website", {"url": url})
        print("Call result:", s)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(arg))


