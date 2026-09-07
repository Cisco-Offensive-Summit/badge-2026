# Storage Transfer Module

`src/badge/storage_sync.py` contains reusable badge storage transfer logic used by the Storage app.

## Responsibilities

| Function | Purpose |
|---|---|
| `is_ignored(path, include_mpy=False)` | Returns true for `.mpy` files when not opted in, bytecode/cache paths, host OS metadata, and editor scratch files that should not be synced |
| `ensure_dirs_exist(path)` | Creates parent directories before restore writes a file |
| `iter_files(root="/", include_mpy=False)` | Recursively scans badge files using badge-relative paths and skips `.mpy` files by default |
| `file_hash(path)` | Computes an MD5 hash for a badge-relative file path |
| `build_manifest(root="/", status=None, include_mpy=False)` | Returns a list of `{path, hash}` dictionaries, caches hashes by size/mtime in `/.storage_manifest_cache.json`, skips `.mpy` files by default, and can report scan/hash status |
| `request_backup_files(wifi, manifest, include_mpy=False)` | Calls `POST /badge/storage/backup/manifest` with `ignore_suffixes` and returns requested uploads |
| `upload_file(wifi, path, expected_hash=None)` | Uploads one file to `POST /badge/storage/backup/upload`, reusing the manifest hash when provided |
| `request_restore_manifest(wifi, include_mpy=False)` | Calls `POST /badge/storage/restore/manifest` with `ignore_suffixes` and returns server files |
| `download_file(wifi, path)` | Downloads one file from `GET /badge/storage/restore/download` and writes it locally |
| `filter_paths(paths, include_mpy=False)` | Applies the same ignore rules to already-planned transfer path lists before upload/download |
| `backup_plan(wifi, status=None, include_mpy=False)` | Returns local manifest plus local-only, server-only, and changed path lists for backup decisions and can report scan/server-check status |
| `restore_plan(wifi, status=None, include_mpy=False)` | Returns badge-only, server-only, and changed path lists for restore decisions and can report server-check/scan status |
| `backup(wifi, progress=None, start=None, error=None, delete_server=True, ..., status=None, include_mpy=False)` | Runs the upload workflow, optionally allowing server-side reconciliation deletes, and skips `.mpy` files by default |
| `restore(wifi, progress=None, start=None, error=None, delete_local=False, ..., status=None, include_mpy=False)` | Runs the download workflow, optionally deleting badge-only local files, and skips `.mpy` files by default |
| `delete_local_file(path)` | Deletes one local badge file |

## Server API usage

All JSON requests include `uniqueID` from `secrets.UNIQUE_ID` and use `Content-Type: application/json`. The module normalizes `wifi.host` with endpoint paths, so hosts work with or without a trailing slash.

| Method | Path | Payload |
|---|---|---|
| `POST` | `/badge/storage/backup/manifest` | `uniqueID`, `ignore_suffixes`, `files: [{path, hash}]` |
| `POST` | `/badge/storage/backup/upload` | `uniqueID`, `file`, `content`, optional `encoding`, `hash` |
| `POST` | `/badge/storage/restore/manifest` | `uniqueID`, `ignore_suffixes` |
| `GET` | `/badge/storage/restore/download` | `uniqueID`, `file` |

Text files are uploaded as string content. Files that cannot be read as text are uploaded with `encoding: "base64"`. The Storage app sends `ignore_suffixes: [".mpy"]` unless the user opts in at the `Check .mpy files too?` prompt, so server-side manifests omit `.mpy` files in the default flow. Storage hashes are MD5 for fast change detection on badge hardware; they are not intended as a security boundary.

## Progress callbacks

The manifest/planning and high-level transfer helpers accept optional callbacks:

- `status(message)` reports non-transfer phases such as scanning local files, hashing individual paths, checking server files, preparing backup/restore, preparing upload/download, and deleting local files. The Storage app uses this to keep the LCD moving during phases that may otherwise look stuck.
- `start(total)` runs after the transfer list is known and before files move. The Storage app uses this to refresh the EPD with `Backing up X Files` or `Downloading X Files`.
- `progress(path, index, total)` runs before each file transfer. The Storage app uses this to show the path and `On X of Y` on the LCD.
- `error(path, exc)` runs when an individual upload or download is rejected or fails. The Storage app shows the failed path on the LCD and a shortened transfer-failed message on the EPD. The transfer continues with the next file and returns `(total, failed)`.

## Destructive sync behavior

Backup previews files that exist only on the server before invoking the server's destructive manifest reconciliation. If the user declines deletion, the badge does not call the destructive backup manifest endpoint and instead uploads badge-only and changed files directly.

Restore previews files that exist only on the badge. Server-only and changed files are downloaded whether the user confirms or declines local deletion. Badge-only files are deleted only when the user confirms.
