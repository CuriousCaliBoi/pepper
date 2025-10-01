from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from mcp import StdioServerParameters


@dataclass
class ServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class ResolvedServer:
    name: str
    params: StdioServerParameters


@dataclass
class ToolDefinition:
    name: str
    description: str
    schema: Dict[str, Any]
