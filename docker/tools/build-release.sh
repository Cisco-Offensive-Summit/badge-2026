#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# build-release.sh
#
# Produces a single flashable image containing the firmware AND a preloaded
# CIRCUITPY filesystem:
#
#   build/build-offsummit_2026/firmware.bin   (built by build-firmware)
#   + src/<files from firmware/release.toml>
#   + a generated secrets.py (from the env file)
#   -> build/release/<BADGE_OUTPUT_NAME>.bin
#
# Run from the repo root with badge-2026-dev/ bind-mounted at /work:
#
#   podman run --rm -v "$(pwd)":/work \
#     --env-file ~/badge-secrets/india.env \
#     -e BADGE_OUTPUT_NAME=firmware-india \
#     --entrypoint bash badge-2026-builder /work/docker/tools/build-release.sh
#
# For a public/demo image that must NOT be able to provision with the server,
# add BADGE_PUBLIC_IMAGE=1. That mode still preloads the filesystem and
# generated secrets.py, but deliberately omits /provisioning_secret.txt and does
# not require BADGE_PROVISIONING_SECRET.
#
# podman reads --env-file host-side, so credentials never need to be inside the
# repo. They are also never written into the repo working tree by this script.
# ---------------------------------------------------------------------------

BADGE_ROOT="${BADGE_ROOT:-/work}"
CONFIG="${BADGE_RELEASE_CONFIG:-${BADGE_ROOT}/firmware/release.toml}"
OUTPUT_NAME="${BADGE_OUTPUT_NAME:-firmware}"
BOARD="${BOARD:-offsummit_2026}"
PUBLIC_IMAGE="${BADGE_PUBLIC_IMAGE:-0}"
SRC_DIR="${BADGE_ROOT}/src"
FW_BIN="${BADGE_ROOT}/build/build-${BOARD}/firmware.bin"
OUT_DIR="${BADGE_ROOT}/build/release"

# Flash layout — must match the partition table. See PLAN.md "Authoritative
# Flash Map"; verified against the on-device partition table binary.
USER_FS_OFFSET=$((0x450000))
USER_FS_SIZE=12255232          # 23936 sectors * 512
FLASH_SIZE=$((0x1000000))      # 16 MB

COLOR_RESET="\033[0m"; COLOR_INFO="\033[1;36m"; COLOR_OK="\033[1;32m"
COLOR_WARN="\033[1;33m"; COLOR_ERR="\033[1;31m"
banner() { printf "\n${COLOR_INFO}========== %s ==========${COLOR_RESET}\n\n" "$1"; }
ok()     { printf "\n${COLOR_OK}>>> %s${COLOR_RESET}\n\n" "$1"; }
warn()   { printf "${COLOR_WARN}[WARN] %s${COLOR_RESET}\n" "$1"; }
die()    { printf "${COLOR_ERR}[ERR] %s${COLOR_RESET}\n" "$1" >&2; exit 1; }

# Staging happens outside the repo so a generated secrets.py can never turn up
# in git status.
STAGE="$(mktemp -d /tmp/badge-stage.XXXXXX)"
WORKDIR="$(mktemp -d /tmp/badge-img.XXXXXX)"
cleanup() { rm -rf "${STAGE}" "${WORKDIR}"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Check 1 — inputs present
# ---------------------------------------------------------------------------
banner "Validating inputs"

[ -f "${CONFIG}" ] || die "config not found: ${CONFIG}"
[ -d "${SRC_DIR}" ] || die "src/ not found at ${SRC_DIR} — is the repo bind-mounted at /work?"
[ -f "${FW_BIN}" ] || die "firmware not found: ${FW_BIN}
Build it first — see the build-firmware skill."

for tool in mformat mcopy mdir python3; do
    command -v "${tool}" >/dev/null 2>&1 || die "missing required tool: ${tool}"
done

# Required when running as root over a bind mount, or git refuses the repo as
# "dubious ownership" and build-info records an unknown commit.
git config --global --add safe.directory "${BADGE_ROOT}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Check 2 — credentials supplied and non-empty
# ---------------------------------------------------------------------------
case "${PUBLIC_IMAGE}" in
    1|true|TRUE|yes|YES) PUBLIC_IMAGE=1 ;;
    0|false|FALSE|no|NO|"") PUBLIC_IMAGE=0 ;;
    *) die "BADGE_PUBLIC_IMAGE must be 0/1, true/false, or yes/no" ;;
esac

: "${BADGE_WIFI_NETWORK:?BADGE_WIFI_NETWORK is unset — pass --env-file with your campus credentials}"
: "${BADGE_WIFI_PASS:?BADGE_WIFI_PASS is unset — pass --env-file with your campus credentials}"
[ -n "${BADGE_WIFI_NETWORK}" ] || die "BADGE_WIFI_NETWORK is empty"
[ -n "${BADGE_WIFI_PASS}" ]    || die "BADGE_WIFI_PASS is empty"

if [ "${PUBLIC_IMAGE}" -eq 1 ]; then
    [ -z "${BADGE_PROVISIONING_SECRET:-}" ] \
        || die "BADGE_PUBLIC_IMAGE=1 refuses BADGE_PROVISIONING_SECRET. Remove it from the environment/env-file."
else
    : "${BADGE_PROVISIONING_SECRET:?BADGE_PROVISIONING_SECRET is unset — pass --env-file with the conference provisioning secret, or set BADGE_PUBLIC_IMAGE=1 for a non-provisioning public image}"
    [ -n "${BADGE_PROVISIONING_SECRET}" ] || die "BADGE_PROVISIONING_SECRET is empty"
fi

# ---------------------------------------------------------------------------
# Check 3 — no UNIQUE_ID anywhere in the environment
# Every badge must provision its own via get_token(); a shared one makes every
# badge after the first fail registration with 409.
# ---------------------------------------------------------------------------
if env | grep -qE '^[A-Z_]*UNIQUE_ID='; then
    die "UNIQUE_ID is present in the environment. Remove it — each badge must
provision its own identity via get_token() on first boot."
fi

# ---------------------------------------------------------------------------
# Read config (TOML via stdlib tomllib; no extra dependency)
# ---------------------------------------------------------------------------
banner "Reading ${CONFIG}"

CONFIG_VARS="$(python3 - "${CONFIG}" <<'PY'
import sys, tomllib, shlex
with open(sys.argv[1], "rb") as f:
    cfg = tomllib.load(f)
rel = cfg.get("release", {})
fs = cfg.get("filesystem", {})
files = fs.get("files") or []
if not files:
    sys.exit("[ERR] filesystem.files is empty in the config")
print("CFG_VERSION=%s" % shlex.quote(str(rel.get("version", "0.0"))))
print("CFG_HOST=%s" % shlex.quote(str(rel.get("host_address", ""))))
print("CFG_FILES=%s" % shlex.quote("\n".join(files)))
PY
)" || die "failed to parse ${CONFIG}"
eval "${CONFIG_VARS}"

# env overrides the config file
HOST_ADDRESS="${BADGE_HOST_ADDRESS:-${CFG_HOST}}"
[ -n "${HOST_ADDRESS}" ] || die "no host address — set it in ${CONFIG} or pass BADGE_HOST_ADDRESS"

echo "  version      : ${CFG_VERSION}"
echo "  host address : ${HOST_ADDRESS}"
echo "  wifi ssid    : ${BADGE_WIFI_NETWORK}"
echo "  wifi pass    : (${#BADGE_WIFI_PASS} chars, not shown)"
if [ "${PUBLIC_IMAGE}" -eq 1 ]; then
    echo "  provisioning : omitted (public image; cannot self-provision)"
else
    echo "  provisioning : (${#BADGE_PROVISIONING_SECRET} chars, not shown)"
fi
echo "  output       : ${OUTPUT_NAME}.bin"

# ---------------------------------------------------------------------------
# Check 4 + stage the filesystem
# ---------------------------------------------------------------------------
banner "Staging filesystem"

while IFS= read -r entry; do
    [ -n "${entry}" ] || continue
    case "${entry}" in
        secrets.py|/*|*..*)
            die "refusing config entry '${entry}' — secrets.py is generated, and absolute/parent paths are not allowed"
            ;;
    esac
    src="${SRC_DIR}/${entry%/}"
    [ -e "${src}" ] || die "config lists '${entry}' but ${src} does not exist"
    dest="${STAGE}/${entry%/}"
    mkdir -p "$(dirname "${dest}")"
    if [ -d "${src}" ]; then
        cp -r "${src}" "${dest}"
        # Bytecode caches from a dev machine must not ship.
        find "${dest}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
        printf "  dir   %-18s %s files\n" "${entry}" "$(find "${dest}" -type f | wc -l | tr -d ' ')"
    else
        cp "${src}" "${dest}"
        printf "  file  %-18s %s bytes\n" "${entry}" "$(stat -c %s "${dest}")"
    fi
done <<< "${CFG_FILES}"

# Generated secrets.py — deliberately WITHOUT UNIQUE_ID.
cat > "${STAGE}/secrets.py" <<EOF
# Generated by build-release.sh — do not edit on the badge, it will be
# overwritten by the next reflash.
#
# UNIQUE_ID is intentionally absent: boot.py catches the ImportError and runs
# get_token() so each badge provisions its own identity.

## Wifi Network
WIFI_NETWORK = "${BADGE_WIFI_NETWORK}"
WIFI_PASS    = "${BADGE_WIFI_PASS}"

## Registration
HOST_ADDRESS = "${HOST_ADDRESS}"
EOF
printf "  gen   %-18s %s bytes\n" "secrets.py" "$(stat -c %s "${STAGE}/secrets.py")"

# Temporary first-boot provisioning credential. Generated from the private env
# file into the staged filesystem only; never written into the repo checkout.
# Public images deliberately omit it so they cannot self-provision with the
# production server.
if [ "${PUBLIC_IMAGE}" -eq 1 ]; then
    printf "  skip  %-18s public image\n" "provisioning_secret.txt"
else
    printf "%s\n" "${BADGE_PROVISIONING_SECRET}" > "${STAGE}/provisioning_secret.txt"
    printf "  gen   %-18s %s bytes\n" "provisioning_secret.txt" "$(stat -c %s "${STAGE}/provisioning_secret.txt")"
fi

# Look for an actual assignment, not a mention. The generated file explains in a
# comment why UNIQUE_ID is absent, and app sources legitimately read
# secrets.UNIQUE_ID — neither should trip this.
while IFS= read -r sfile; do
    if grep -Eq '^[[:space:]]*UNIQUE_ID[[:space:]]*=' "${sfile}"; then
        die "${sfile#${STAGE}/} defines UNIQUE_ID — refusing to build.
Each badge must provision its own identity via get_token() on first boot."
    fi
done < <(find "${STAGE}" -name 'secrets.py')

STAGED_FILES="$(cd "${STAGE}" && find . -type f | sed 's|^\./||' | sort)"
STAGED_COUNT="$(printf '%s\n' "${STAGED_FILES}" | wc -l | tr -d ' ')"
STAGED_BYTES="$(du -sb "${STAGE}" | cut -f1)"
echo
echo "  staged ${STAGED_COUNT} files, ${STAGED_BYTES} bytes"
[ "${STAGED_BYTES}" -lt "${USER_FS_SIZE}" ] \
    || die "staged content (${STAGED_BYTES} B) exceeds the user_fs partition (${USER_FS_SIZE} B)"

# ---------------------------------------------------------------------------
# Build the FAT image
#
# Geometry matches what CircuitPython itself formats, read from a badge's live
# CIRCUITPY boot sector: 512 B sectors, 4 sectors/cluster, 1 reserved sector,
# 1 FAT, 512 root entries, 23936 total sectors -> FAT16.
#
# Two mtools quirks, both hit during development:
#   - mformat will NOT create the image file; it must be pre-sized.
#   - -r is in SECTORS, not entries. -r 32 == 512 entries (16 per sector).
#     -r 512 silently yields 8192 entries and a 23-sector FAT.
# ---------------------------------------------------------------------------
banner "Building user_fs image"

FS_IMG="${WORKDIR}/user_fs.img"
truncate -s "${USER_FS_SIZE}" "${FS_IMG}"
mformat -i "${FS_IMG}" -M 512 -c 4 -r 32 -R 1 -d 1 -T 23936 -v CIRCUITPY ::
(cd "${STAGE}" && mcopy -i "${FS_IMG}" -s -Q -o ./* ::)

echo "  contents:"
mdir -i "${FS_IMG}" :: | sed 's/^/    /'

python3 - "${FS_IMG}" <<'PY'
import struct, sys
b = open(sys.argv[1], "rb").read(512)
want = {"bytes_per_sector": (struct.unpack("<H", b[11:13])[0], 512),
        "sectors_per_cluster": (b[13], 4),
        "reserved_sectors": (struct.unpack("<H", b[14:16])[0], 1),
        "num_fats": (b[16], 1),
        "root_entries": (struct.unpack("<H", b[17:19])[0], 512),
        "total_sectors": (struct.unpack("<H", b[19:21])[0], 23936),
        "media": (b[21], 0xF8),
        "fat_sectors": (struct.unpack("<H", b[22:24])[0], 24)}
bad = [k for k, (got, exp) in want.items() if got != exp]
for k, (got, exp) in want.items():
    print("    %-20s %-6s (expect %s)%s" % (k, got, exp, "  <-- MISMATCH" if got != exp else ""))
label = b[43:54].decode(errors="replace").strip()
print("    %-20s %r" % ("volume label", label))
if bad:
    sys.exit("[ERR] boot sector mismatch: %s" % ", ".join(bad))
PY
ok "user_fs image verified against CircuitPython's geometry"

# ---------------------------------------------------------------------------
# Merge firmware + filesystem
#
# Done in Python rather than `esptool merge_bin` so this does not depend on the
# ESP-IDF environment being activated. Gaps are padded with 0xFF to match flash
# erase state, exactly as esptool would.
# ---------------------------------------------------------------------------
banner "Merging firmware + filesystem"

mkdir -p "${OUT_DIR}"
OUT_BIN="${OUT_DIR}/${OUTPUT_NAME}.bin"

python3 - "${FW_BIN}" "${FS_IMG}" "${OUT_BIN}" "${USER_FS_OFFSET}" "${FLASH_SIZE}" <<'PY'
import sys
fw_path, fs_path, out_path, fs_off, flash_size = sys.argv[1:6]
fs_off, flash_size = int(fs_off), int(flash_size)
fw = open(fw_path, "rb").read()
fs = open(fs_path, "rb").read()
if len(fw) > fs_off:
    sys.exit("[ERR] firmware (%d B) overruns the user_fs offset (%d)" % (len(fw), fs_off))
if fs_off + len(fs) > flash_size:
    sys.exit("[ERR] filesystem overruns the end of flash")
img = bytearray(b"\xff" * flash_size)
img[0:len(fw)] = fw
img[fs_off:fs_off + len(fs)] = fs
open(out_path, "wb").write(img)
print("    firmware   : %9d bytes at 0x0" % len(fw))
print("    filesystem : %9d bytes at 0x%x" % (len(fs), fs_off))
print("    total      : %9d bytes" % len(img))
PY

# ---------------------------------------------------------------------------
# Build info (never records credentials)
# ---------------------------------------------------------------------------
INFO="${OUT_DIR}/${OUTPUT_NAME}.build-info.txt"
GIT_REV="$(git -C "${BADGE_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY=""
git -C "${BADGE_ROOT}" diff --quiet 2>/dev/null || GIT_DIRTY=" (dirty)"
{
    echo "output          : ${OUTPUT_NAME}.bin"
    echo "built           : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "release version : ${CFG_VERSION}"
    echo "board           : ${BOARD}"
    echo "git commit      : ${GIT_REV}${GIT_DIRTY}"
    echo "host address    : ${HOST_ADDRESS}"
    echo "wifi ssid       : ${BADGE_WIFI_NETWORK}"
    echo "wifi password   : (not recorded)"
    if [ "${PUBLIC_IMAGE}" -eq 1 ]; then
        echo "provisioning    : omitted — public/non-provisioning image"
        echo "unique id       : absent; this image cannot self-provision without /provisioning_secret.txt"
    else
        echo "provisioning    : present in image as /provisioning_secret.txt (not recorded)"
        echo "unique id       : absent by design — provisioned per badge via get_token()"
    fi
    echo "user_fs offset  : $(printf '0x%x' "${USER_FS_OFFSET}")"
    echo "flash size      : $(printf '0x%x' "${FLASH_SIZE}")"
    echo
    echo "staged files (${STAGED_COUNT}):"
    printf '%s\n' "${STAGED_FILES}" | sed 's/^/  /'
} > "${INFO}"

ok "Release image at ${OUT_BIN}"
ls -l "${OUT_BIN}" "${INFO}" | sed 's/^/  /'
echo
echo "Flash with (badge must be in download mode):"
echo "  esptool --chip esp32s3 -p /dev/ttyACM0 -b 921600 --no-stub \\"
echo "      --before no_reset write_flash 0x0 ${OUTPUT_NAME}.bin"
echo
warn "This image OVERWRITES the whole flash including user_fs — any existing"
warn "badge secrets.py (and its UNIQUE_ID) will be lost. Back it up first."
if [ "${PUBLIC_IMAGE}" -eq 1 ]; then
    warn "Public image mode was enabled: /provisioning_secret.txt is absent, so"
    warn "freshly flashed badges cannot self-provision with the badge server."
fi
