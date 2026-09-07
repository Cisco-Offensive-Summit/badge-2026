import json
import os
import secrets
from binascii import b2a_base64

import adafruit_hashlib as hashlib


IGNORED_DIRS = ("__pycache__", ".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems")
HASH_ALGORITHM = "md5"
MANIFEST_CACHE_PATH = "/.storage_manifest_cache.json"
IGNORED_NAMES = (
    ".DS_Store",
    ".metadata_never_index",
    ".VolumeIcon.icns",
    "Thumbs.db",
    "desktop.ini",
    MANIFEST_CACHE_PATH.strip("/"),
)
IGNORED_PREFIXES = ("._", ".Trash-")
IGNORED_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo", "~")
OPTIONAL_MPY_SUFFIX = ".mpy"
CHUNK_SIZE = 4096
STATUS_INTERVAL = 10


class StorageSyncError(Exception):
    pass


def is_ignored(path, include_mpy=False):
    clean_path = path.strip("/")
    parts = clean_path.split("/")
    name = parts[-1] if parts else clean_path
    for part in parts:
        if part in IGNORED_DIRS:
            return True
    if name in IGNORED_NAMES:
        return True
    for prefix in IGNORED_PREFIXES:
        if name.startswith(prefix):
            return True
    if not include_mpy and clean_path.endswith(OPTIONAL_MPY_SUFFIX):
        return True
    for suffix in IGNORED_SUFFIXES:
        if clean_path.endswith(suffix):
            return True
    return False


def ensure_dirs_exist(path):
    parts = path.strip("/").split("/")[:-1]
    current_path = ""
    for part in parts:
        current_path = current_path + "/" + part if current_path else part
        try:
            os.mkdir(current_path)
        except OSError:
            pass


def is_dir(path):
    try:
        return bool(os.stat(path)[0] & 0x4000)
    except OSError:
        return False


def iter_files(root="/", include_mpy=False):
    for name in os.listdir(root):
        full_path = root.rstrip("/") + "/" + name if root != "/" else "/" + name
        rel_path = full_path.strip("/")
        if is_ignored(rel_path, include_mpy):
            continue
        if is_dir(full_path):
            for child in iter_files(full_path, include_mpy):
                yield child
        else:
            yield rel_path


def file_hash(path):
    digest = hashlib.md5()
    with open("/" + path.strip("/"), "rb") as infile:
        while True:
            chunk = infile.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path):
    try:
        stat = os.stat("/" + path.strip("/"))
        return stat[6], stat[8]
    except (OSError, IndexError):
        return None, None


def load_manifest_cache():
    try:
        with open(MANIFEST_CACHE_PATH, "r") as infile:
            cache = json.load(infile)
        if cache.get("algorithm") != HASH_ALGORITHM:
            return {}
        files = cache.get("files", {})
        if isinstance(files, dict):
            return files
    except (OSError, ValueError):
        pass
    return {}


def save_manifest_cache(cache):
    try:
        with open(MANIFEST_CACHE_PATH, "w") as outfile:
            json.dump({"algorithm": HASH_ALGORITHM, "files": cache}, outfile)
            outfile.flush()
    except OSError:
        pass


def cached_file_hash(path, cache, next_cache):
    size, mtime = file_fingerprint(path)
    cached = cache.get(path)
    if (
        cached
        and mtime is not None
        and cached.get("size") == size
        and cached.get("mtime") == mtime
        and cached.get("hash")
    ):
        file_hash_value = cached.get("hash")
    else:
        file_hash_value = file_hash(path)
    next_cache[path] = {"size": size, "mtime": mtime, "hash": file_hash_value}
    return file_hash_value


def build_manifest(root="/", status=None, include_mpy=False):
    if status:
        status("Scanning local files")
    files = []
    cache = load_manifest_cache()
    next_cache = {}
    for index, path in enumerate(iter_files(root, include_mpy), 1):
        if status and (index == 1 or index % STATUS_INTERVAL == 0):
            status("Hashing " + str(index) + " files\n" + path)
        files.append({"path": path, "hash": cached_file_hash(path, cache, next_cache)})
    save_manifest_cache(next_cache)
    return files


def item_path(item):
    return item.get("path") or item.get("file")


def manifest_map(files, include_mpy=False):
    result = {}
    for item in files:
        path = item_path(item)
        if path and not is_ignored(path, include_mpy):
            result[path] = item.get("hash")
    return result


def api_url(wifi, path):
    return wifi.host.rstrip("/") + "/" + path.lstrip("/")


def ignore_suffixes(include_mpy=False):
    return [] if include_mpy else [OPTIONAL_MPY_SUFFIX]


def request_backup_files(wifi, manifest, include_mpy=False):
    body = {"uniqueID": secrets.UNIQUE_ID, "files": manifest, "ignore_suffixes": ignore_suffixes(include_mpy)}
    rsp = wifi.requests(method="POST", url=api_url(wifi, "badge/storage/backup/manifest"), json=body, headers=json_headers())
    return response_files(rsp)


def request_restore_manifest(wifi, include_mpy=False):
    body = {"uniqueID": secrets.UNIQUE_ID, "ignore_suffixes": ignore_suffixes(include_mpy)}
    rsp = wifi.requests(method="POST", url=api_url(wifi, "badge/storage/restore/manifest"), json=body, headers=json_headers())
    return response_files(rsp)


def response_files(rsp):
    try:
        if rsp.status_code >= 400:
            raise StorageSyncError("Server returned " + str(rsp.status_code))
        body = rsp.json()
        return body.get("files", [])
    finally:
        close_response(rsp)


def json_headers():
    return {"Accept": "application/json", "Content-Type": "application/json"}


def close_response(rsp):
    try:
        rsp.close()
    except Exception:
        pass


def upload_file(wifi, path, expected_hash=None):
    clean_path = path.strip("/")
    content, encoding = read_upload_content(clean_path)
    payload = {"uniqueID": secrets.UNIQUE_ID, "file": clean_path, "hash": expected_hash or file_hash(clean_path), "content": content}
    if encoding:
        payload["encoding"] = encoding
    rsp = wifi.requests(method="POST", url=api_url(wifi, "badge/storage/backup/upload"), json=payload, headers=json_headers())
    try:
        if rsp.status_code >= 400:
            raise StorageSyncError("Upload failed " + str(rsp.status_code) + " " + clean_path)
    finally:
        close_response(rsp)


def read_upload_content(path):
    with open("/" + path.strip("/"), "rb") as infile:
        data = infile.read()
    try:
        return data.decode("utf-8"), None
    except UnicodeError:
        return b2a_base64(data).strip().decode("utf-8"), "base64"


def download_file(wifi, path):
    clean_path = path.strip("/")
    body = {"uniqueID": secrets.UNIQUE_ID, "file": clean_path}
    rsp = wifi.requests(method="GET", url=api_url(wifi, "badge/storage/restore/download"), json=body, headers=json_headers(), stream=True)
    try:
        if rsp.status_code >= 400:
            raise StorageSyncError("Download failed " + str(rsp.status_code) + " " + clean_path)
        local_path = "/" + clean_path
        ensure_dirs_exist(local_path)
        with open(local_path, "wb") as outfile:
            for chunk in rsp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    outfile.write(chunk)
            # Sync once per file. Syncing after every 4 KiB chunk makes restore
            # painfully slow in the simulator (host-wide os.sync) and on badge
            # flash, while not adding useful durability for a single-file write.
            outfile.flush()
            os.sync()
    finally:
        close_response(rsp)


def diff_manifests(local_manifest, server_manifest, include_mpy=False):
    local_files = manifest_map(local_manifest, include_mpy)
    server_files = manifest_map(server_manifest, include_mpy)
    local_only = []
    server_only = []
    changed = []
    for path, local_hash in local_files.items():
        server_hash = server_files.get(path)
        if server_hash is None:
            local_only.append(path)
        elif server_hash != local_hash:
            changed.append(path)
    for path in server_files:
        if path not in local_files:
            server_only.append(path)
    return local_only, server_only, changed


def filter_paths(paths, include_mpy=False):
    result = []
    for path in paths:
        if not is_ignored(path, include_mpy):
            result.append(path)
    return result


def transfer_uploads(wifi, paths, progress=None, start=None, error=None, manifest=None):
    total = len(paths)
    failed = 0
    hashes = manifest_map(manifest or [])
    if start:
        start(total)
    for index, path in enumerate(paths):
        if progress:
            progress(path, index + 1, total)
        try:
            upload_file(wifi, path, expected_hash=hashes.get(path))
        except StorageSyncError as exc:
            failed += 1
            if error:
                error(path, exc)
    return total, failed


def transfer_downloads(wifi, paths, progress=None, start=None, error=None):
    total = len(paths)
    failed = 0
    if start:
        start(total)
    for index, path in enumerate(paths):
        if progress:
            progress(path, index + 1, total)
        try:
            download_file(wifi, path)
        except StorageSyncError as exc:
            failed += 1
            if error:
                error(path, exc)
    return total, failed


def backup_plan(wifi, status=None, include_mpy=False):
    local_manifest = build_manifest(status=status, include_mpy=include_mpy)
    if status:
        status("Checking server files")
    server_manifest = request_restore_manifest(wifi, include_mpy=include_mpy)
    if status:
        status("Preparing backup")
    local_only, server_only, changed = diff_manifests(local_manifest, server_manifest, include_mpy)
    return local_manifest, local_only, server_only, changed


def backup(wifi, progress=None, start=None, error=None, delete_server=True, local_manifest=None, local_only=None, changed=None, status=None, include_mpy=False):
    if local_manifest is None or local_only is None or changed is None:
        local_manifest, local_only, server_only, changed = backup_plan(wifi, status=status, include_mpy=include_mpy)
    if delete_server:
        if status:
            status("Checking backup files")
        requested = []
        for item in request_backup_files(wifi, local_manifest, include_mpy=include_mpy):
            path = item_path(item)
            if path and not is_ignored(path, include_mpy):
                requested.append(path)
    else:
        requested = filter_paths(local_only + changed, include_mpy)
    if status:
        status("Preparing upload")
    return transfer_uploads(wifi, requested, progress, start, error, manifest=local_manifest)


def restore_plan(wifi, status=None, include_mpy=False):
    if status:
        status("Checking server files")
    server_manifest = request_restore_manifest(wifi, include_mpy=include_mpy)
    local_manifest = build_manifest(status=status, include_mpy=include_mpy)
    if status:
        status("Preparing restore")
    local_only, server_only, changed = diff_manifests(local_manifest, server_manifest, include_mpy)
    return local_only, server_only, changed


def delete_local_file(path):
    os.remove("/" + path.strip("/"))


def restore(wifi, progress=None, start=None, error=None, delete_local=False, local_only=None, server_only=None, changed=None, status=None, include_mpy=False):
    if local_only is None or server_only is None or changed is None:
        local_only, server_only, changed = restore_plan(wifi, status=status, include_mpy=include_mpy)
    if status:
        status("Preparing download")
    downloads = filter_paths(server_only + changed, include_mpy)
    total, failed = transfer_downloads(wifi, downloads, progress, start, error)
    if delete_local:
        if status:
            status("Deleting local files")
        for path in local_only:
            try:
                delete_local_file(path)
            except OSError as exc:
                failed += 1
                if error:
                    error(path, exc)
    return total, failed
