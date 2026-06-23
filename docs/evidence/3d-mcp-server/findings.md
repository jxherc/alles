# stage 3d - alles as an MCP server - audit findings (2026-06-23)

## current state
- `routes/mcp.py` makes alles an MCP **client**: it stores external MCP server configs, connects to
  them, lists + calls THEIR tools (`mcp_call_tool`). there is NO server side - nothing exposes alles's
  OWN capabilities so an external agent (Claude Desktop, another alles) could drive it.
- the 3a registry now holds every tool with name + schema + scope - exactly the catalog an MCP
  `tools/list` needs - but nothing serves it over the protocol.

## the gap
- a JSON-RPC 2.0 handler implementing the MCP methods (initialize, tools/list, tools/call, ping) that
  surfaces the 3a capability registry as MCP tools and routes calls through `capabilities.invoke`.
- an HTTP transport endpoint (the SSE/streamable-HTTP transport's POST channel) so external clients can
  reach it. a stdio launcher can reuse the same handler.

## fix
- `services/mcp_server.py`: `handle(req)` async -> dispatch the MCP methods; `_tool_list()` maps
  registry tools to `{name, description, inputSchema}`; `_call()` -> capabilities.invoke ->
  `{content:[{type:text,text}], isError}`. JSON-RPC envelope, notifications (no id) return None.
- route POST /api/mcp/rpc -> handle(); returns 204 for notifications.

tested: initialize handshake, tools/list carries the registry + schema, tools/call invokes (stub) +
returns content, error -> isError, unknown method -> -32601, ping, notification -> no response, id
echoed, endpoint POST round-trip.
