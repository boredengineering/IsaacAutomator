# RunPod MCP Server

Connect AI tools to Runpod using the Model Context Protocol for infrastructure management and documentation access.

https://docs.runpod.io/get-started/mcp-servers

Runpod provides two Model Context Protocol (MCP) servers that connect AI tools and coding agents directly to Runpod:
- **Runpod API MCP server:** Manage Pods, endpoints, templates, volumes, and registries through the Runpod REST API. Requires a Runpod API key.
- **Runpod docs MCP server:** Search Runpod documentation for features, code examples, and guides. No authentication required.


## Runpod API MCP server

The Runpod API MCP server gives AI tools access to the Runpod REST API, letting you create and manage Pods, Serverless endpoints, templates, network volumes, and container registries through natural language.

- **Endpoint:** Available via npm package ```@runpod/mcp-server```
- **Source code:** [github.com/runpod/runpod-mcp](https://github.com/runpod/runpod-mcp)
- **Authentication:** Requires a Runpod API key

Supported clients:

- Claude Code
- Codex CLI
- Cursor
- VS Code with Copilot
- Claude Desktop
- Windsurf
- Cline
- Gemini CLI

### Claude Code

```bash
claude mcp add runpod --scope user -e RUNPOD_API_KEY=your_api_key_here -- npx -y @runpod/mcp-server@latest
```

Replace your_api_key_here with your Runpod API key. The --scope user flag makes the server available across all your projects. Run /mcp inside Claude Code to verify the connection.

### Codex CLI

```bash
codex mcp add runpod --env RUNPOD_API_KEY=your_api_key_here -- npx -y @runpod/mcp-server@latest
```

### Cursor

Add the following to .cursor/mcp.json (project-level) or ~/.cursor/mcp.json (global). This configuration works with both the Cursor IDE and the Cursor Agent:

```json
{
  "mcpServers": {
    "runpod": {
      "command": "npx",
      "args": ["-y", "@runpod/mcp-server@latest"],
      "env": {
        "RUNPOD_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### VS Code with Copilot

1. Open the Command Palette (Ctrl+Shift+P on Windows/Linux or Cmd+Shift+P on macOS).
2. Run MCP: Add Server and select stdio.
3. Enter the following details:
    - Name: Runpod
    - Command: npx
    - Arguments: -y @runpod/mcp-server@latest
4. Add environment variable RUNPOD_API_KEY with your Runpod API key.
5. Select Global or Workspace and click Add.


### Claude Desktop

Add the following to your Claude Desktop config file:

- macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
- Windows: %APPDATA%\Claude\claude_desktop_config.json

```json
{
  "mcpServers": {
    "runpod": {
      "command": "npx",
      "args": ["-y", "@runpod/mcp-server@latest"],
      "env": {
        "RUNPOD_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Restart Claude Desktop after saving the file.

### Windsurf

Edit ~/.codeium/windsurf/mcp_config.json (or open from Settings > Cascade > MCP Servers > View raw config):

```json
{
  "mcpServers": {
    "runpod": {
      "command": "npx",
      "args": ["-y", "@runpod/mcp-server@latest"],
      "env": {
        "RUNPOD_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Cline

Open the Cline sidebar in VS Code, click the MCP Servers icon, then select Configure MCP Servers to edit cline_mcp_settings.json:

```json
{
  "mcpServers": {
    "runpod": {
      "command": "npx",
      "args": ["-y", "@runpod/mcp-server@latest"],
      "env": {
        "RUNPOD_API_KEY": "your_api_key_here"
      },
      "disabled": false
    }
  }
}
```

### Gemini CLI

Add to ~/.gemini/settings.json (global) or .gemini/settings.json (project-level):

```json
{
  "mcpServers": {
    "runpod": {
      "command": "npx",
      "args": ["-y", "@runpod/mcp-server@latest"],
      "env": {
        "RUNPOD_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Other clients

For any other MCP-compatible client, use the following connection details:

- Command: npx
- Args: -y @runpod/mcp-server@latest
- Environment: RUNPOD_API_KEY=your_api_key_here

### Usage examples

Once connected, you can interact with your Runpod resources using natural language:

```text
List all my Runpod Pods
```

```text
Create a new Runpod Pod with the following specifications:
- Name: ml-training-pod
- Image: runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04
- GPU Type: NVIDIA GeForce RTX 4090
- GPU Count: 1
- Cloud Type: SECURE
```

```text
Create a Runpod Serverless endpoint with the following configuration:
- Name: image-generation-endpoint
- Template ID: 30zmvf89kd
- Minimum workers: 0
- Maximum workers: 5
```

```text
Stop the Pod named "ml-training-pod"
```

## Runpod docs MCP server

The Runpod docs MCP server provides access to Runpod’s documentation knowledge base, making it easier to get answers about features and how to use them.

- **Endpoint:** https://docs.runpod.io/mcp
- **Authentication:** None required


### Claude Code

```bash
claude mcp add runpod-docs --scope user --transport http https://docs.runpod.io/mcp
```

### Codex CLI

```bash
codex mcp add runpod-docs --url https://docs.runpod.io/mcp
```

### Cursor

Add to your .cursor/mcp.json file:

```json
{
  "mcpServers": {
    "runpod-docs": {
      "url": "https://docs.runpod.io/mcp"
    }
  }
}
```

### VS Code with Copilot

1. Open the Command Palette (Ctrl+Shift+P on Windows/Linux or Cmd+Shift+P on macOS).
2. Run MCP: Add Server and select HTTP.
3. Enter https://docs.runpod.io/mcp as the URL and Runpod Docs as the name.
4. Select Global or Workspace and click Add.

### Claude Desktop

1. Open Settings in Claude Desktop.
2. Navigate to Connectors and select Add custom connector.
3. Enter https://docs.runpod.io/mcp as the URL and click Add.

### Windsurf

Add to ~/.codeium/windsurf/mcp_config.json:

```json
{
  "mcpServers": {
    "runpod-docs": {
      "serverUrl": "https://docs.runpod.io/mcp"
    }
  }
}
```

### Cline

Add to cline_mcp_settings.json:

```json
{
  "mcpServers": {
    "runpod-docs": {
      "url": "https://docs.runpod.io/mcp",
      "disabled": false
    }
  }
}
```

### Gemini CLI

Add to ~/.gemini/settings.json. Note that Gemini CLI uses httpUrl instead of url:

```json
{
  "mcpServers": {
    "runpod-docs": {
      "httpUrl": "https://docs.runpod.io/mcp"
    }
  }
}
```

### Other clients

For any other MCP-compatible client, use URL https://docs.runpod.io/mcp (HTTP transport).


### Usage Example

With the docs MCP server connected, you can ask questions about Runpod features:

```text
Explain the Runpod Serverless model caching feature
```

```text
How do I configure environment variables for a Serverless endpoint?
```

```text
How does global networking work in Runpod?
```

