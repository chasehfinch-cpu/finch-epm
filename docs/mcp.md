# finch-epm MCP Server

finch-epm includes a built-in MCP (Model Context Protocol) server that lets any MCP-capable AI client interact with your local data catalog, query cached data, and generate validated dashboards.

## Quick start

```
finch-epm mcp
```

This starts the MCP server in stdio mode. MCP clients connect by launching this command as a subprocess.

## Tools

The server exposes these tools to the connected LLM:

| Tool | Description |
|------|-------------|
| `list_sources` | List all configured data profiles with connector types |
| `list_tables` | List tables in a profile's catalog with access status |
| `describe_table` | Get full column list for a table |
| `preview_rows` | Fetch sample rows to see real data values |
| `query_cache` | Execute read-only SQL against the local DuckDB cache |
| `validate_fdash` | Parse and validate a .fdash dashboard candidate |
| `write_fdash` | Write a validated .fdash file to disk |
| `open_fdash` | Open a dashboard in the browser |
| `get_dimension_hierarchy` | Get hierarchy for a dimensional entity |
| `list_themes` | List available dashboard theme presets |

The `query_cache` tool uses sqlglot to parse and validate SQL. Only SELECT and WITH...SELECT statements are allowed. INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, and all other mutation statements are rejected.

## Resources

| Resource URI | Description |
|---|---|
| `fdash://spec` | The complete DASHBOARDS.md specification |
| `fdash://catalog/{profile}` | Compact JSON summary of a profile's catalog |
| `fdash://themes` | Available theme presets |
| `fdash://examples` | Canonical .fdash examples for few-shot prompting |

## Client configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "finch-epm": {
      "command": "finch-epm",
      "args": ["mcp"]
    }
  }
}
```

On macOS this file is at `~/Library/Application Support/Claude/claude_desktop_config.json`.
On Windows it is at `%APPDATA%\Claude\claude_desktop_config.json`.

### Claude Code

```
claude mcp add finch-epm -- finch-epm mcp
```

Or add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "finch-epm": {
      "command": "finch-epm",
      "args": ["mcp"]
    }
  }
}
```

### Cursor

Add to your Cursor MCP settings (Settings > MCP Servers):

```json
{
  "finch-epm": {
    "command": "finch-epm",
    "args": ["mcp"]
  }
}
```

### ChatGPT Desktop

ChatGPT Desktop MCP support is in development. When available, the configuration will be similar to Claude Desktop.

### Any MCP client (generic)

The finch-epm MCP server speaks the standard MCP stdio protocol. Launch it as a subprocess:

```
finch-epm mcp
```

For HTTP-based clients, use SSE transport:

```
finch-epm mcp --transport sse --port 8808
```

## Troubleshooting

### "command not found: finch-epm"

The MCP client needs `finch-epm` on its PATH. If you installed with pip in a virtualenv, use the full path:

```json
{
  "command": "/path/to/venv/bin/finch-epm",
  "args": ["mcp"]
}
```

On Windows:

```json
{
  "command": "C:\\Users\\you\\venv\\Scripts\\finch-epm.exe",
  "args": ["mcp"]
}
```

### "No data sources configured"

Run `finch-epm setup` first to connect and crawl at least one data source. The MCP server reads from the same local catalog and cache as the CLI.

### Server starts but tools fail

Make sure you have synced data: `finch-epm sync -c <connector> -p <profile> --all`. The MCP server queries the local DuckDB cache, which is only populated after sync.

### Stdio connection hangs

Some MCP clients require the server to respond within a timeout. If `finch-epm mcp` takes too long to start (e.g., because of a slow keyring), try running `finch-epm llm list` first to warm up the keyring.
