from __future__ import annotations

import os
import shutil
import sys
from typing import Dict, List

import yaml
from mcp import StdioServerParameters

from .types import ResolvedServer, ServerConfig


def _default_config_path() -> str:
    explicit = os.getenv("TOOL_CONFIG_PATH")
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(__file__), "tools.yaml")


def _interpolate_env(value: str) -> str:
    # format: ${env:VAR}
    if isinstance(value, str) and value.startswith("${env:") and value.endswith("}"):
        var_name = value[len("${env:") : -1]
        return os.environ.get(var_name, value)
    return value


def load_tools_yaml(config_path: str | None) -> List[ServerConfig]:
    path = config_path or _default_config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping object")

    servers = data.get("servers")
    if not isinstance(servers, list):
        raise ValueError("Config must contain 'servers' as a list")

    server_configs: List[ServerConfig] = []
    for i, item in enumerate(servers):
        if not isinstance(item, dict):
            raise ValueError(f"Server entry at index {i} must be a mapping")

        name = item.get("name")
        command = item.get("command")
        args = item.get("args", [])
        env = item.get("env", {})

        if not name or not command:
            raise ValueError(f"Server entry at index {i} requires 'name' and 'command'")

        if not isinstance(args, list):
            raise ValueError(f"'args' for server '{name}' must be a list of strings")
        if not isinstance(env, dict):
            raise ValueError(f"'env' for server '{name}' must be a mapping of strings")

        # Interpolate env placeholders
        interpolated_env: Dict[str, str] = {}
        for k, v in env.items():
            interpolated_env[str(k)] = str(_interpolate_env(v))

        server_configs.append(
            ServerConfig(
                name=name,
                command=str(command),
                args=[str(a) for a in args],
                env=interpolated_env,
            )
        )

    return server_configs


def build_stdio_params(servers: List[ServerConfig]) -> List[ResolvedServer]:
    resolved: List[ResolvedServer] = []
    for s in servers:
        # Resolve the python executable to the current interpreter when requested
        # This ensures child MCP processes run inside the same conda env
        command = s.command
        if command in ("python", "python3"):
            command = sys.executable

        # Best-effort check that the command exists
        cmd_exists = shutil.which(command) is not None
        if not cmd_exists and os.path.sep in command:
            cmd_exists = os.path.exists(command)
        if not cmd_exists:
            # We still allow it, but flag as ValueError per spec
            raise ValueError(f"Executable for server '{s.name}' not found: {command}")

        # Merge the current process environment with per-server overrides so
        # child MCP processes inherit all necessary variables (API keys, etc.).
        merged_env = dict(os.environ)
        if s.env:
            merged_env.update(s.env)
        params = StdioServerParameters(
            command=command, args=s.args or None, env=merged_env
        )
        resolved.append(ResolvedServer(name=s.name, params=params))

    return resolved
