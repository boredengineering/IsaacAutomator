# ------------------------------------------------------------------------------
# Stage 1: Base Image with Official Kasm Jammy Desktop (Ubuntu 22.04)
# ------------------------------------------------------------------------------
FROM kasmweb/ubuntu-jammy-desktop:1.14.0

USER root

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    NVIDIA_DRIVER_CAPABILITIES=graphics,compat32,utility,compute \
    VNC_PW=vncpassword \
    VNC_VIEW_ONLY_PW=vncviewonlypassword

# ------------------------------------------------------------------------------
# Stage 2: Install CUDA 11.8 & cuDNN 8 Repositories
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg2 \
    ca-certificates \
    curl \
    lsb-release \
    && wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.0-1_all.deb \
    && dpkg -i cuda-keyring_1.0-1_all.deb \
    && rm cuda-keyring_1.0-1_all.deb

# ------------------------------------------------------------------------------
# Stage 3: Install Core GPU Libraries, VirtualGL, and Development Tools
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # CUDA Toolkit & Deep Learning primitives
    cuda-toolkit-11-8 \
    libcudnn8 \
    libcudnn8-dev \
    libnccl2 \
    libnccl-dev \
    # VirtualGL for 3D OpenGL Acceleration over VNC
    virtualgl \
    mesa-utils \
    # Native Python 3.10 Development stack
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    # Core utilities
    build-essential \
    git \
    htop \
    tmux \
    ffmpeg \
    xclip \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Stage 4: VirtualGL Configuration & Permissions
# ------------------------------------------------------------------------------
# Configure VirtualGL to grant access to non-root users
RUN vglserver_config -config +s +f +t

# Ensure python3 points to python3.10
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# ------------------------------------------------------------------------------
# Stage 5: User & Entrypoint Setup
# ------------------------------------------------------------------------------
USER 1000
WORKDIR /home/kasm-user

CMD ["--wait"]