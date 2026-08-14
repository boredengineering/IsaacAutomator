# ==============================================================================
# Isaac Automator - Standardized Cloud-Native DevContainer
# ==============================================================================

FROM ubuntu:24.04

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
    gnupg \
    gnupg2 \
    curl \
    wget \
    git \
    unzip \
    rsync \
    nano \
    jq \
    ripgrep \
    dnsutils \
    lsb-release \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

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

# Base Python packages for CLI orchestration and development
RUN pip install --no-cache-dir --break-system-packages \
    click \
    randomname \
    pwgen \
    debugpy \
    ansible \
    requests

# Create state directory mount points
RUN mkdir -p /app/state/.aws /app/state/.gcp /app/state/.azure /opt/tf-data

# Persistent bash history & prompt configuration
RUN echo 'export HISTFILE=/app/state/.bash_history' >> /root/.bashrc && \
    echo 'export HISTSIZE=10000' >> /root/.bashrc && \
    echo 'export HISTFILESIZE=20000' >> /root/.bashrc && \
    echo 'shopt -s histappend' >> /root/.bashrc && \
    echo 'export PROMPT_COMMAND="history -a; ${PROMPT_COMMAND}"' >> /root/.bashrc && \
    echo "export PS1='\[\033[01;33m\][Isaac Automator \[\033[00;33m\]\${VERSION:-dev}\[\033[01;33m\]]\[\033[00m\]:\w\$ '" >> /root/.bashrc

WORKDIR /app