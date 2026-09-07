#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# build-badgelibs.sh
#
# Compiles the badge's own Python libraries to .mpy using mpy-cross.
#
#   /work/badgelibs/*.py   ->   /work/build/badgelibs/*.mpy
#
# badgelibs/ holds the plaintext source of truth. The generated .mpy files are
# copied into src/lib/ by hand and committed, which is why the output goes to
# build/ rather than straight into src/.
#
# This does NOT need the ESP-IDF toolchain — only mpy-cross, which is a plain
# host binary. If mpy-cross has not been built yet (i.e. no firmware build has
# run in this checkout) it is built here, which takes well under a minute.
#
# Run from the repo root with badge-2026-dev/ bind-mounted at /work:
#
#   podman run --rm -v /path/to/badge-2026:/work --entrypoint bash \
#       badge-2026-builder /work/docker/tools/build-badgelibs.sh
#
# mpy-cross is an ARM/Linux ELF built inside the container, so it cannot run on
# a macOS host — this has to go through the container.
# ---------------------------------------------------------------------------

BADGE_ROOT="${BADGE_ROOT:-/work}"
REPO_ROOT="${REPO_ROOT:-/work/circuitpython}"
JOBS="${JOBS:-$(nproc)}"

SRC_DIR="${BADGE_ROOT}/badgelibs"
OUT_DIR="${BADGE_ROOT}/build/badgelibs"
MPY_CROSS="${REPO_ROOT}/mpy-cross/build/mpy-cross"

COLOR_RESET="\033[0m"
COLOR_INFO="\033[1;36m"
COLOR_OK="\033[1;32m"
COLOR_ERR="\033[1;31m"

print_banner() { printf "\n${COLOR_INFO}========== %s ==========${COLOR_RESET}\n\n" "$1"; }
print_done()   { printf "\n${COLOR_OK}>>> %s${COLOR_RESET}\n\n" "$1"; }
print_err()    { printf "${COLOR_ERR}[ERR] %s${COLOR_RESET}\n" "$1" >&2; }

# ---------------------------------------------------------------------------
# Validate mounts
# ---------------------------------------------------------------------------
if [ ! -d "${SRC_DIR}" ]; then
    print_err "badgelibs source directory not found at ${SRC_DIR}"
    print_err "Bind-mount badge-2026-dev/ at /work."
    exit 1
fi

if [ ! -d "${REPO_ROOT}" ]; then
    print_err "circuitpython submodule not found at ${REPO_ROOT}"
    print_err "Run: git submodule update --init --recursive"
    exit 1
fi

# Required when running as root over a bind mount, otherwise git refuses to
# operate on the submodule during the mpy-cross build.
git config --global --add safe.directory "${REPO_ROOT}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Ensure mpy-cross
# ---------------------------------------------------------------------------
if [ -x "${MPY_CROSS}" ]; then
    print_banner "Using existing mpy-cross"
else
    print_banner "Building mpy-cross"
    make -C "${REPO_ROOT}/mpy-cross" -j"${JOBS}"
    print_done "mpy-cross build complete"
fi

if [ ! -x "${MPY_CROSS}" ]; then
    print_err "mpy-cross missing or not executable at ${MPY_CROSS}"
    exit 1
fi

"${MPY_CROSS}" --version

# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------
print_banner "Compiling badgelibs -> .mpy"

mkdir -p "${OUT_DIR}"
# Clear stale output so a deleted source cannot leave an orphan .mpy behind
# that would then get copied into src/lib/.
rm -f "${OUT_DIR}"/*.mpy

count=0
failed=0
for src in "${SRC_DIR}"/*.py; do
    [ -e "${src}" ] || continue
    name="$(basename "${src}" .py)"
    out="${OUT_DIR}/${name}.mpy"

    if "${MPY_CROSS}" -o "${out}" "${src}"; then
        in_size=$(stat -c %s "${src}")
        out_size=$(stat -c %s "${out}")
        printf "  %-22s %6d -> %6d bytes (%d%%)\n" \
            "${name}" "${in_size}" "${out_size}" $((out_size * 100 / in_size))
        count=$((count + 1))
    else
        print_err "failed to compile ${src}"
        failed=$((failed + 1))
    fi
done

if [ "${failed}" -ne 0 ]; then
    print_err "${failed} file(s) failed to compile"
    exit 1
fi

if [ "${count}" -eq 0 ]; then
    print_err "no .py files found in ${SRC_DIR}"
    exit 1
fi

print_done "Compiled ${count} library file(s) to ${OUT_DIR}/"

echo "Next: copy ${OUT_DIR}/*.mpy into src/lib/ and commit them."
echo "The .py sources stay in badgelibs/ as the source of truth."
