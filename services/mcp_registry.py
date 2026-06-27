"""shared MCP runtime registry — live client sessions + their tool lists, keyed by server id.

lives in its own leaf module (imports nothing) so routes/mcp.py (which manages the connections)
and services/agent_tools.py (which calls the tools) can both reach the same dicts without the
routes->services->routes import cycle they had when this state lived in routes/mcp.py.
"""

sessions: dict[str, object] = {}  # server_id -> mcp ClientSession
tools: dict[str, list] = {}  # server_id -> [{name, description, schema}]
