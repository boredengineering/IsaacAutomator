# Base image with Playwright dependencies and browsers pre-installed
FROM mcr.microsoft.com/playwright:v1.58.2-jammy

# Set shell and environment variables
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Update system and install essential tools, Python, and base libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    dirmngr \
    gnupg2 \
    ca-certificates \
    curl \
    wget \
    git \
    git-lfs \
    ripgrep \
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

# Install Git LFS
RUN git lfs install

# Install Quarto CLI
RUN QUARTO_VERSION=$(curl -s https://api.github.com/repos/quarto-dev/quarto-cli/releases/latest | grep -oP '"tag_name": "\K[^"]+') && \
    wget -q https://github.com/quarto-dev/quarto-cli/releases/download/${QUARTO_VERSION}/quarto-${QUARTO_VERSION#v}-linux-amd64.deb && \
    dpkg -i quarto-${QUARTO_VERSION#v}-linux-amd64.deb && \
    rm quarto-${QUARTO_VERSION#v}-linux-amd64.deb

# Install global node packages (Claude Code)
RUN npm install -g @anthropic-ai/claude-code

# Install Antigravity CLI (agy)
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash && \
    ln -sf /root/.local/bin/agy /usr/local/bin/agy

# Install UV
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /root/.local/bin/uv /usr/local/bin/uv && \
    ln -sf /root/.local/bin/uvx /usr/local/bin/uvx

# Install Python packages
RUN pip install --no-cache-dir jupyter ipykernel usd-core "huggingface_hub[cli]"

# Install R packages needed for development
RUN Rscript -e 'install.packages(c("languageserver", "renv"), repos="https://cloud.r-project.org")'

# Install Hermes Agent
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup --skip-browser

# Set agent browser executable path in root bashrc and global bashrc
RUN echo "export AGENT_BROWSER_EXECUTABLE_PATH=\$(find /ms-playwright -name chrome -type f | head -n 1)" >> /root/.bashrc && \
    echo "export AGENT_BROWSER_EXECUTABLE_PATH=\$(find /ms-playwright -name chrome -type f | head -n 1)" >> /etc/bash.bashrc
