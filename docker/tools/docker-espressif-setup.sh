#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# docker-espressif-setup.sh
#
# Bootstraps the ESP-IDF toolchain and builds CircuitPython firmware for the
# Offensive Summit badge.
#
# Expected container layout (badge-2026-dev/ bind-mounted at /work):
#
#   /work/
#   ├── circuitpython/          ← git submodule (Cisco-Offensive-Summit fork)
#   ├── firmware/
#   │   └── offsummit_2026/     ← board definition source of truth
#   └── ...
#
# The board definition is copied from /work/firmware/<BOARD>/ into the
# circuitpython boards directory before the build runs. It is not committed
# into the submodule — badge-2026-dev/firmware/ is the canonical source.
# ---------------------------------------------------------------------------

BADGE_ROOT="${BADGE_ROOT:-/work}"
REPO_ROOT="${REPO_ROOT:-/work/circuitpython}"
JOBS="${JOBS:-$(nproc)}"
BOARD="${BOARD:-offsummit_2026}"
REUSE_SETUP="${REUSE_SETUP:-1}"
STATE_DIR="${STATE_DIR:-/opt/cp-build-state}"
SETUP_MARKER="${STATE_DIR}/espressif_setup_done"

COLOR_RESET="\033[0m"
COLOR_INFO="\033[1;36m"
COLOR_OK="\033[1;32m"
COLOR_WARN="\033[1;33m"
COLOR_ERR="\033[1;31m"

print_banner() {
    printf "\n${COLOR_INFO}========== %s ==========${COLOR_RESET}\n\n" "$1"
}

print_done() {
    printf "\n${COLOR_OK}>>> %s${COLOR_RESET}\n\n" "$1"
}

print_warn() {
    printf "${COLOR_WARN}[WARN] %s${COLOR_RESET}\n" "$1"
}

print_err() {
    printf "${COLOR_ERR}[ERR] %s${COLOR_RESET}\n" "$1" >&2
}

# ---------------------------------------------------------------------------
# Validate mounts
# ---------------------------------------------------------------------------
if [ ! -d "${REPO_ROOT}" ]; then
    print_err "circuitpython submodule not found at ${REPO_ROOT}"
    print_err "Did you initialise the submodule? Run:"
    print_err "  git submodule update --init --recursive"
    print_err "and re-run the container with badge-2026-dev/ bind-mounted at /work."
    exit 1
fi

# ---------------------------------------------------------------------------
# Mark repos as git-safe (required when running as root over a bind mount)
# ---------------------------------------------------------------------------
mark_git_safe() {
    print_banner "Marking repositories as safe for git"
    git config --global --add safe.directory "${REPO_ROOT}"
    git config --global --add safe.directory "${REPO_ROOT}/ports/espressif"
    git config --global --add safe.directory "${REPO_ROOT}/ports/espressif/esp-idf"

    if [ -d "${REPO_ROOT}/frozen" ]; then
        for repo_dir in "${REPO_ROOT}"/frozen/*; do
            [ -d "${repo_dir}" ] && \
                git config --global --add safe.directory "${repo_dir}"
        done
    fi
    print_done "Git safe-directory configuration complete"
}

mkdir -p "${STATE_DIR}"
mark_git_safe

# ---------------------------------------------------------------------------
# Install board definition
#
# badge-2026-dev/firmware/<BOARD>/ is the source of truth for the board files.
# Copy them into the circuitpython tree before every build so the correct
# version is always used, regardless of what is committed in the submodule.
# ---------------------------------------------------------------------------
install_board() {
    local src="${BADGE_ROOT}/firmware/${BOARD}"
    local dst="${REPO_ROOT}/ports/espressif/boards/${BOARD}"

    if [ ! -d "${src}" ]; then
        print_err "Board definition not found at ${src}"
        exit 2
    fi

    print_banner "Installing board definition: ${BOARD}"
    mkdir -p "${dst}"
    cp -r "${src}/." "${dst}/"
    print_done "Board installed: ${dst}"
}

install_board

# ---------------------------------------------------------------------------
# One-time toolchain setup (skipped when REUSE_SETUP=1 and marker exists)
# ---------------------------------------------------------------------------
if [ "${REUSE_SETUP}" = "1" ] && [ -f "${SETUP_MARKER}" ]; then
    print_warn "Reusing previous setup (${SETUP_MARKER}). Set REUSE_SETUP=0 to force."
else
    cd "${REPO_ROOT}/ports/espressif"

    print_banner "Fetching Espressif port submodules"
    make fetch-port-submodules
    print_done "Submodules fetched"

    print_banner "Initialising ESP-IDF internal submodules"
    git -C "${REPO_ROOT}/ports/espressif/esp-idf" submodule update --init --recursive
    print_done "ESP-IDF submodules initialised"

    # Re-mark frozen submodules as safe after they are populated
    mark_git_safe

    # Install CircuitPython dev deps with system Python BEFORE activating the
    # ESP-IDF venv. Installing them after sourcing export.sh would inject them
    # into the ESP-IDF venv and break its own pinned constraints (e.g. cryptography<45).
    cd "${REPO_ROOT}"
    REQ_FILE="requirements-dev.txt"
    [ -f "circuitpython-dev.txt" ] && REQ_FILE="circuitpython-dev.txt"
    print_banner "Installing Python deps from ${REQ_FILE}"
    python3 -m pip install --break-system-packages -r "${REPO_ROOT}/${REQ_FILE}"
    print_done "Python dependencies installed"

    cd "${REPO_ROOT}/ports/espressif"

    print_banner "Installing ESP-IDF toolchain"
    ./esp-idf/install.sh
    print_done "ESP-IDF installation complete"

    print_banner "Activating ESP-IDF environment"
    source ./esp-idf/export.sh

    # Install CircuitPython build-time packages into the ESP-IDF venv.
    # These are needed by scripts invoked during `make` (e.g. gen_web_workflow_static.py)
    # which runs under the activated venv, not the system Python.
    # Only packages with no ESP-IDF constraint conflicts are added here.
    print_banner "Installing CircuitPython build-time packages into ESP-IDF venv"
    pip install minify_html jsmin
    print_done "Build-time packages installed"

    cd "${REPO_ROOT}"
    print_banner "Building mpy-cross"
    make -C mpy-cross -j"${JOBS}"
    print_done "mpy-cross build complete"

    touch "${SETUP_MARKER}"
fi

# ---------------------------------------------------------------------------
# Build firmware
# ---------------------------------------------------------------------------
cd "${REPO_ROOT}/ports/espressif"
source ./esp-idf/export.sh
cd "${REPO_ROOT}"

print_banner "Building board: ${BOARD}"
make -C "${REPO_ROOT}/ports/espressif" \
    BOARD="${BOARD}" \
    BUILD="${BADGE_ROOT}/build/build-${BOARD}" \
    -j"${JOBS}"
print_done "Build complete — firmware at ${BADGE_ROOT}/build/build-${BOARD}/"
