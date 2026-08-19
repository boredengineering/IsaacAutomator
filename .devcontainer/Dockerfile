# ==============================================================================
# Isaac Automator - Standardized Cloud-Native DevContainer
# ==============================================================================

# Base image with Playwright dependencies and browsers pre-installed
FROM mcr.microsoft.com/playwright:v1.58.2-jammy

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
ENV force_color_prompt=yes

# Core dependencies and utilities
RUN apt-get update && apt-get install -qy --no-install-recommends \
    software-properties-common \
    ca-certificates \
    openssh-client \
    apt-transport-https \
    apt-utils \
    dirmngr \
    gnupg \
    gnupg2 \
    curl \
    wget \
    git \
    git-lfs \
    unzip \
    rsync \
    nano \
    jq \
    ripgrep \
    dnsutils \
    lsb-release \
    ffmpeg \
    libmagick++-dev \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Add R CRAN repository and install R (r-base and r-base-dev)
RUN wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | gpg --dearmor -o /usr/share/keyrings/cran-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cran-archive-keyring.gpg] https://cloud.r-project.org/bin/linux/ubuntu jammy-cran40/" | tee /etc/apt/sources.list.d/cran.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    r-base \
    r-base-dev \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI repository and gh
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Initialize Git LFS and configure Git to use GitHub CLI credential helper
RUN git lfs install && \
    git config --system "credential.https://github.com.helper" "" && \
    git config --system --add "credential.https://github.com.helper" "!/usr/bin/gh auth git-credential" && \
    git config --system "credential.https://gist.github.com.helper" "" && \
    git config --system --add "credential.https://gist.github.com.helper" "!/usr/bin/gh auth git-credential"

# Install Google Cloud CLI
RUN curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# Install Alibaba Cloud CLI (not in standard devcontainer features)
RUN /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/aliyun/aliyun-cli/HEAD/install.sh)" \
    && aliyun auto-completion || true

# Install official HashiCorp Terraform MCP Server binary
RUN curl -fsSL -o /tmp/tf-mcp.zip https://releases.hashicorp.com/terraform-mcp-server/1.2.0/terraform-mcp-server_1.2.0_linux_amd64.zip \
    && unzip -q /tmp/tf-mcp.zip -d /tmp/ \
    && mv /tmp/terraform-mcp-server /usr/local/bin/ \
    && chmod +x /usr/local/bin/terraform-mcp-server \
    && rm -rf /tmp/tf-mcp*

# Install UV (fast Python package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /root/.local/bin/uv /usr/local/bin/uv && \
    ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

# Install global node packages (Claude Code)
# Note: npm is available automatically via the playwright base image
RUN npm install -g @anthropic-ai/claude-code

# Install Antigravity CLI (agy)
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash && \
    ln -sf /root/.local/bin/agy /usr/local/bin/agy

# Install Hermes Agent
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup --skip-browser

# Base Python packages for CLI orchestration and development
RUN pip3 install --no-cache-dir \
    click \
    randomname \
    pwgen \
    debugpy \
    ansible \
    requests \
    jupyter \
    ipykernel \
    usd-core \
    "huggingface_hub[cli]"

# Install R packages needed for development
RUN Rscript -e 'install.packages(c("languageserver", "renv"), repos="https://cloud.r-project.org")'

# Create state directory mount points
RUN mkdir -p /app/state/.aws /app/state/.gcp /app/state/.azure /opt/tf-data

# Persistent bash history, prompt configuration, and agent browser paths
RUN echo 'export HISTFILE=/app/state/.bash_history' >> /root/.bashrc && \
    echo 'export HISTSIZE=10000' >> /root/.bashrc && \
    echo 'export HISTFILESIZE=20000' >> /root/.bashrc && \
    echo 'shopt -s histappend' >> /root/.bashrc && \
    echo 'export PROMPT_COMMAND="history -a; ${PROMPT_COMMAND}"' >> /root/.bashrc && \
    echo "export PS1='\[\033[01;33m\][Isaac Automator \[\033[00;33m\]\${VERSION:-dev}\[\033[01;33m\]]\[\033[00m\]:\w\$ '" >> /root/.bashrc && \
    echo "export AGENT_BROWSER_EXECUTABLE_PATH=\$(find /ms-playwright -name chrome -type f | head -n 1)" >> /root/.bashrc && \
    echo "export AGENT_BROWSER_EXECUTABLE_PATH=\$(find /ms-playwright -name chrome -type f | head -n 1)" >> /etc/bash.bashrc && \
    echo '# Auto-load host-persisted keys (~/.gemini/.env or ~/.claude/.env)' >> /root/.bashrc && \
    echo '[ -f /root/.gemini/.env ] && set -a && . /root/.gemini/.env && set +a' >> /root/.bashrc && \
    echo '[ -f /root/.claude/.env ] && set -a && . /root/.claude/.env && set +a' >> /root/.bashrc && \
    echo '[ -f /root/.gemini/.env ] && set -a && . /root/.gemini/.env && set +a' >> /etc/bash.bashrc && \
    echo '[ -f /root/.claude/.env ] && set -a && . /root/.claude/.env && set +a' >> /etc/bash.bashrc && \
    echo 'command -v gh &>/dev/null && ! git config --global --get credential.https://github.com.helper &>/dev/null && gh auth setup-git 2>/dev/null || true' >> /root/.bashrc && \
    echo 'command -v gh &>/dev/null && ! git config --global --get credential.https://github.com.helper &>/dev/null && gh auth setup-git 2>/dev/null || true' >> /etc/bash.bashrc

# Helper script for setting keys into host-persisted storage
RUN echo '#!/bin/bash' > /usr/local/bin/set-key && \
    echo 'if [ -z "$1" ] || [ -z "$2" ]; then' >> /usr/local/bin/set-key && \
    echo '    echo "Usage: set-key <KEY_NAME> <VALUE>"' >> /usr/local/bin/set-key && \
    echo '    echo "Example: set-key ANTHROPIC_API_KEY sk-ant-..."' >> /usr/local/bin/set-key && \
    echo '    exit 1' >> /usr/local/bin/set-key && \
    echo 'fi' >> /usr/local/bin/set-key && \
    echo 'mkdir -p /root/.gemini' >> /usr/local/bin/set-key && \
    echo '[ -f /root/.gemini/.env ] && sed -i "/^$1=/d" /root/.gemini/.env' >> /usr/local/bin/set-key && \
    echo 'echo "$1=\"$2\"" >> /root/.gemini/.env' >> /usr/local/bin/set-key && \
    echo 'chmod 600 /root/.gemini/.env' >> /usr/local/bin/set-key && \
    echo 'echo "Saved $1 to host storage (~/.gemini/.env). Run source ~/.bashrc or open a new terminal to use it."' >> /usr/local/bin/set-key && \
    chmod +x /usr/local/bin/set-key

WORKDIR /app