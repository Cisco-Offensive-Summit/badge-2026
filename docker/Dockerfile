FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN /bin/bash -c 'apt-get update && apt-get install -y --no-install-recommends \
    bash \
    bison \
    build-essential \
    ca-certificates \
    ccache \
    cmake \
    curl \
    dfu-util \
    flex \
    gdb-multiarch \
    git \
    gperf \
    libffi-dev \
    libssl-dev \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    make \
    mtools \
    ninja-build \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    rsync \
    unzip \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*'

# Use root for bind-mounted repo writes (.git/config, submodules, etc.).
USER root

# badge-2026 repo root is mounted at /work.
# The circuitpython submodule lives at /work/circuitpython.
WORKDIR /work

# ESP-IDF tools and caches kept in stable, mount-friendly paths.
ENV BADGE_ROOT=/work
ENV REPO_ROOT=/work/circuitpython
ENV IDF_TOOLS_PATH=/work/.espressif
ENV PIP_CACHE_DIR=/work/.cache/pip
ENV CCACHE_DIR=/work/.cache/ccache
ENV PATH=/usr/lib/ccache:${PATH}
ENV BOARD=offsummit_2026
ENV REUSE_SETUP=1
ENV STATE_DIR=/work/.build-state

# Helper script is baked into the image at build time.
# Build context must be badge-2026/docker/ so the tools/ path resolves.
COPY tools/docker-espressif-setup.sh /usr/local/bin/docker-espressif-setup.sh
RUN chmod +x /usr/local/bin/docker-espressif-setup.sh

CMD ["/usr/local/bin/docker-espressif-setup.sh"]
