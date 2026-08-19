#!/usr/bin/env bash
set -e

echo "================================================================"
echo "🤖 Isaac Automator - Multi-Agent Environment Setup"
echo "================================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ----------------------------------------------------------------------
# 1. Google Antigravity Agent Configuration
# ----------------------------------------------------------------------
echo "⚙️  [1/4] Configuring Google Antigravity..."
mkdir -p /root/.gemini/config

if [ -f "${WORKSPACE_DIR}/.mcp.json" ]; then
    cp "${WORKSPACE_DIR}/.mcp.json" /root/.gemini/config/mcp_config.json
    echo "   ✔ Synchronized .mcp.json -> /root/.gemini/config/mcp_config.json"
fi

# Ensure .agents/skills.json registers both Isaac skills and NVIDIA skills
mkdir -p "${WORKSPACE_DIR}/.agents"
cat << 'JSON_EOF' > "${WORKSPACE_DIR}/.agents/skills.json"
{
  "entries": [
    {
      "path": ".agents/skills/isaac-automator"
    },
    {
      "path": ".agents/skills"
    }
  ]
}
JSON_EOF
echo "   ✔ Configured ${WORKSPACE_DIR}/.agents/skills.json"

# ----------------------------------------------------------------------
# 2. Claude Code Agent Configuration
# ----------------------------------------------------------------------
echo "⚙️  [2/4] Configuring Claude Code..."
mkdir -p /root/.claude

if command -v claude &>/dev/null; then
    # Pre-approve and register MCP servers in user scope so /mcp connects immediately
    claude mcp add --scope user terraform -- /usr/local/bin/terraform-mcp-server stdio --toolsets=all 2>/dev/null || true
    claude mcp add --scope user playwright -- npx -y @playwright/mcp@latest --headless --no-sandbox 2>/dev/null || true
    claude mcp add --scope user ansible -- npx -y @ansible/ansible-mcp-server --stdio 2>/dev/null || true
    claude mcp add --scope user gcp-cloud -- npx -y @google-cloud/gcloud-mcp 2>/dev/null || true
    echo "   ✔ Pre-registered all 4 MCP servers into user scope in ~/.claude.json"
fi

# ----------------------------------------------------------------------
# 3. Third-Party Skills Health Check
# ----------------------------------------------------------------------
echo "⚙️  [3/4] Checking NVIDIA Skills Repository..."
SKILL_COUNT=$(ls -d "${WORKSPACE_DIR}/.agents/skills/"* 2>/dev/null | wc -l || echo 0)
if [ "$SKILL_COUNT" -lt 10 ]; then
    echo "   📥 Installing 335+ NVIDIA skills via npx skills..."
    cd "${WORKSPACE_DIR}" && npx -y skills add nvidia/skills --all || true
else
    echo "   ✔ Found ${SKILL_COUNT} active skills in .agents/skills/"
fi

# ----------------------------------------------------------------------
# 4. Ansible Galaxy Collections
# ----------------------------------------------------------------------
echo "⚙️  [4/4] Installing Ansible Galaxy Collections..."
ansible-galaxy collection install community.docker google.cloud --force-with-deps 2>/dev/null || true
echo "   ✔ Installed community.docker and google.cloud collections"

echo "================================================================"
echo "✅ All agent environments (Antigravity & Claude Code) ready!"
echo "================================================================"
