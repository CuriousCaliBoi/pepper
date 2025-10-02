#!/usr/bin/env bash

# ----------------------------------------------------------------------------
# Pepper - Environment variables template
# ----------------------------------------------------------------------------
# How to use:
# 1) Copy this file to env_var.sh
#      cp env_var.example.sh env_var.sh
# 2) Edit env_var.sh and fill in your real values
# 3) Load it in your shell before running services:
#      source env_var.sh
# 4) python -m pepper.launch_pepper
#
# IMPORTANT: Do NOT commit env_var.sh with real keys.
# ----------------------------------------------------------------------------
# ============================================================================
# Required (must fill before running)
# ============================================================================
# OpenAI (LLM calls)
export OPENAI_API_KEY="your-openai-api-key"

# Composio (tool auth for Gmail/Calendar/etc.)
export COMPOSIO_API_KEY="your-composio-api-key"

# ============================================================================
# Recommended (safe defaults or leave blank)
# ============================================================================

export SERPER_API_KEY="" # for google search

# ============================================================================
# Optional (safe defaults or leave blank)
# ============================================================================
# Context Store (pepper feeds, subscriptions). Leave as-is for local dev or blank to disable.
export CONTEXT_STORE_ENDPOINT="http://localhost:8000"
export CONTEXT_STORE_API_KEY="your-context-store-api-key"

# --- Optional search providers (used by searching tools) ---
export JINA_API_KEY=""

# --- Optional: Anthropic (if you enable Anthropic models) ---
export ANTHROPIC_API_KEY=""

# --- Optional: Langfuse (monitoring/telemetry) ---
export LANGFUSE_SECRET_KEY=""
export LANGFUSE_PUBLIC_KEY=""
export LANGFUSE_HOST="https://us.cloud.langfuse.com"

export REMINDER_BASE_URL=http://localhost:8060
export REMINDER_API_KEY=abc

# Notes:
# - Only OPENAI_API_KEY and COMPOSIO_API_KEY are required.
# - Everything else is optional and can be left at defaults/blank.
# - The scheduler and MCP servers inherit these variables automatically.
# - If you change values, re-run: `source env_var.sh` in the same shell.
