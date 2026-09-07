# Storage App

The Storage app provides the badge UI for server-backed badge file backup and restore.

## Purpose

The app lets a badge sync its CIRCUITPY filesystem with the server's badge-keyed storage under `/badge/storage/*`. It is intended as a Wi-Fi/web replacement for manual USB file backup and restore.

## Files

| File | Purpose |
|---|---|
| `src/apps/storage/code.py` | App entry point, LCD menu, progress UI, and button handling |
| `src/apps/storage/metadata.json` | Launcher metadata for the Storage app |
| `src/apps/storage/boot.json` | Mounts the badge filesystem writable and disables USB drive access while the app runs |
| `src/apps/storage/icon.bmp` | Launcher icon |
| `src/apps/storage/storage_bg.bmp` | Legacy generated Storage EPD background bitmap; the current app uses a simple code-drawn EPD layout instead of a background image |
| `tools/storage_bg.pixelart` | Legacy editable text source for the Storage EPD background bitmap |
| `tools/pixel_art_to_bmp.py` | Helper script for regenerating BMPs from pixel art |
| `src/badge/storage_sync.py` | Shared backup, restore, upload, download, hash, and directory helpers |

## Controls

| Button | Action |
|---|---|
| S4 | Exit to launcher |
| S5 | Move down |
| S6 | Move up |
| S7 | Select Backup, Restore, or Delete |

When launched, the LCD shows a `Backup` / `Restore` / `Delete` list using the shared `scrollable_list` library (`badgelibs/scrollable_list.py`, shipped as `src/lib/scrollable_list.mpy`). Storage keeps list navigation bounded at the top and bottom, uses full-width highlighted rows on the LCD, and leaves long selected filenames or paths on the standard selected-row scrolling behavior to avoid adding button latency. The EPD intentionally uses a simple CorpoBreach-style layout instead of a background image: a centered title, separator lines, centered status text, and rounded button labels in fixed columns. Long EPD-only paths/status lines are shortened so they do not collide with the title or button row.

## Backup workflow

1. After `Backup` is selected, the LCD shows a wrapped `Check .mpy files too?` / `This will take more time` prompt with `No` as the top/default choice and `Yes` below it.
2. With the default `No` choice, `.mpy` files are skipped during local scanning, hashing, manifest comparison, server reconciliation, and upload planning. Choosing `Yes` includes `.mpy` files in the existing backup behavior.
3. The app connects to Wi-Fi using `badge.wifi.WIFI`, then updates the LCD with the acquired IP address.
4. `badge.storage_sync.build_manifest()` scans the local badge filesystem and computes MD5 hashes while reporting periodic LCD status for scanning and hashing. Hashes are cached by file size/mtime in `/.storage_manifest_cache.json` so unchanged files do not need to be reread on later syncs.
5. The app requests the server manifest and checks for files that exist only on the server while reporting the server-check/preparation phase on the LCD.
6. If server-only files exist, the LCD lists them and asks whether they may be deleted from server storage.
7. If deletion is confirmed, the app sends `POST /badge/storage/backup/manifest` with `uniqueID`, `ignore_suffixes`, and the local manifest so the server can reconcile deleted files, then uploads requested files.
8. If deletion is declined, server-only files are left alone and the app still uploads badge-only files and changed files with `POST /badge/storage/backup/upload`.
9. The EPD displays `Backing up X Files` where `X` is the upload count, then shows the backup completion summary.
10. The LCD shows non-transfer phases, then the current transfer path and progress in the form `On X of Y`; these status messages use the shared display wrapper so long paths split within the LCD width.

## Restore workflow

1. After `Restore` is selected, the LCD shows a wrapped `Check .mpy files too?` / `This will take more time` prompt with `No` as the top/default choice and `Yes` below it.
2. With the default `No` choice, `.mpy` files are skipped during server manifest retrieval, local scanning, hashing, comparison, request planning, and downloads. Choosing `Yes` includes `.mpy` files in the existing restore behavior.
3. The app connects to Wi-Fi using `badge.wifi.WIFI`, then updates the LCD with the acquired IP address.
4. The app sends `POST /badge/storage/restore/manifest` with `uniqueID` and `ignore_suffixes` while reporting the server-check phase on the LCD.
5. `badge.storage_sync.build_manifest()` computes local hashes while reporting LCD status for scanning and hashing.
6. The app compares server hashes with local hashes and selects only missing or changed files while reporting the restore-preparation phase on the LCD.
7. If badge-only files exist, the LCD lists them and asks whether they may be deleted from the badge.
8. Server-only files and changed files are downloaded regardless of the delete choice.
9. If deletion is confirmed, badge-only files are deleted after downloads are attempted.
10. If deletion is declined, badge-only files are kept.
11. The EPD displays `Downloading X Files` where `X` is the download count, then shows the restore completion summary.
12. Destination directories are created before files are written.
13. The LCD shows non-transfer phases, then the current transfer path and progress in the form `On X of Y`; these status messages use the shared display wrapper so long paths split within the LCD width.

## Ignore rules

Local manifest, backup upload, and restore download planning ignore Python bytecode/cache artifacts and common host OS metadata:

- `*.mpy` by default, unless the user chooses `Yes` at the `Check .mpy files too?` prompt
- `*.pyc`
- `*.pyo`
- Any path containing `__pycache__/`
- macOS metadata such as `.DS_Store`, AppleDouble `._*` files, `.Trashes`, `.Spotlight-V100`, `.fseventsd`, `.TemporaryItems`, `.metadata_never_index`, and `.VolumeIcon.icns`
- Windows metadata such as `Thumbs.db` and `desktop.ini`
- Editor scratch files ending in `.swp`, `.swo`, or `~`
- The local hash cache `/.storage_manifest_cache.json`

## Delete menu

The `Delete` option opens a local badge file browser rooted at `/`. The EPD renders the navigation labels as rounded buttons. On the main Storage menu S4 is labeled `Exit`; inside confirmation and delete-browser screens S4 is labeled `Back`. Use S5/S6 to move within the bounded list, S7 to select, and S4 to go back. Storage polls button pressed states directly, without starting the shared down/up event tasks, and locks each button until release so quick navigation presses register reliably while the LCD list animates. Long selected filenames use the shared list's standard selected-row scrolling without loop restart to keep button handling responsive. Selecting a directory enters it. Selecting a file opens a `Delete` / `Cancel` confirmation prompt before removing the local file.

