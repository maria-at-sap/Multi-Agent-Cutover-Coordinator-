"""
MCP tool loader — simplified for local MAS deployment.

Returns an empty list so the orchestrator runs purely on its built-in tools
(Sonia / Maria / Silvia). To add MCP tools, populate this function.
"""
import logging

logger = logging.getLogger(__name__)


async def get_mcp_tools() -> list:
    """Return MCP tools. Empty list for standalone local deployment."""
    return []
