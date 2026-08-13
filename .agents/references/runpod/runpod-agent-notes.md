# Agent Skills for RunPod

These Skills can help agents to leverage the RunPod ecosystem.

https://docs.runpod.io/get-started/agent-skills

## Configuring the Skills

Install the skills

```bash
npx skills add runpod/runpod-plugins-official
```

Install runpod CLI

```bash
curl -sSL https://cli.runpod.net | bash
# or with Homebrew:
brew install runpod/runpodctl/runpodctl
```


Authenticate [RunPod API key](https://docs.runpod.io/get-started/api-keys)

```bash
# Set the key for the current shell (add to ~/.zshrc or ~/.bashrc to persist):
export RUNPOD_API_KEY=<key>

# Or save it permanently to ~/.runpod/config.toml:
runpodctl doctor
```

## Testing

Confirm it’s wired up by asking:

> “List my Runpod endpoints”

If your endpoints come back, you’re set

## List of Skills

The plugin installs a router with the following set of focused skills:

| Skill | Description |
|---|---|
| `runpod` | Router and entry point. Reads your task and hands it to the right skill. |
| `runpod-mcp` | Manages Pods, endpoints, templates, network volumes, registries, and billing through the Runpod MCP server. |
| `runpodctl` | Manages the same resources from the Runpod CLI, plus Hub deployments, file transfers, SSH keys, and model caching. |
| `flash` | Writes and deploys your own Python code to Runpod Serverless using the `runpod-flash` SDK. |
| `companion-clis` | Uses supporting CLIs such as Hugging Face, Docker, and the AWS CLI when a task needs them. |
| `runpod-usage` | Provides conceptual knowledge about Pods, Serverless, storage, and GPU selection. |


## Native install options

The npx skills add command above works everywhere. If you’d rather install the plugin through your agent’s native marketplace, use the route for your agent below. Each route installs the same router and skills.

### Claude code

```bash
/plugin marketplace add runpod/runpod-plugins-official
/plugin install runpod@runpod
/reload-plugins
```

Installing the plugin also wires up the hosted Runpod MCP server.

To authenticate it, run /mcp, select runpod, and choose Sign in with Runpod.

### Codex

```bash
codex plugin marketplace add https://github.com/runpod/runpod-plugins-official.git
```

Run codex /plugins, open the Runpod tab, and install (reload if prompted). If the Runpod MCP tools don’t appear, add the hosted server manually:

```bash
codex mcp add runpod --transport http https://mcp.getrunpod.io/
```

### Gemini

Gemini can install the plugin natively through the bundled gemini-extension.json. Follow your client’s extension documentation to add it.

### Connecting the MCP server on other agents

The hosted Runpod MCP server gives your agent structured control-plane tools for managing Pods, endpoints, and other resources. Claude Code sets it up automatically during a native install. On other agents, run the guided installer, which detects your agent and configures the connection:

```bash
npx @runpod/mcp-server@latest add
```

The installer authenticates the MCP server for you. To reuse the API key you already set instead, pass it as a bearer header when you add the server. For example, in Claude Code:

```bash
claude mcp add --transport http runpod -s user https://mcp.getrunpod.io/ \
  --header "Authorization: Bearer $RUNPOD_API_KEY"
```

## Update and uninstall

To update the plugin to the latest version:

```bash
# Claude Code:
/plugin marketplace update runpod

# Codex:
codex plugin marketplace upgrade runpod

# skills.sh:
npx skills add runpod/runpod-plugins-official
```

In Claude Code, run /reload-plugins after updating.

To uninstall:

```bash
# Claude Code:
/plugin uninstall runpod@runpod

# Codex:
codex plugin marketplace remove runpod

# skills.sh:
npx skills remove runpod
```

If a command reports a name mismatch, list what’s installed first with /plugin marketplace list (Claude Code), codex plugin marketplace list (Codex), or npx skills list (skills.sh), then use the name shown.


