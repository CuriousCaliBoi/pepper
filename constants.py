from pathlib import Path

# Paths relative to the pepper directory
PEPPER_DIR = Path(__file__).resolve().parent
AGENT_DIR = PEPPER_DIR / "agent"
TOOL_DIR = PEPPER_DIR / "agent" / "tool"
FEED_DIR = PEPPER_DIR / "feed"

# One level up from pepper (repo root)
REPO_ROOT = PEPPER_DIR.parent

COMPOSIO_USER_ID = "default_user"
