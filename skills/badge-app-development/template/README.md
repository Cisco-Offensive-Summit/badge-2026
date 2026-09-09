# App template

Copy these files into a new folder under `src/apps/`:

```bash
mkdir -p src/apps/greeter
cp skills/badge-app-development/template/code.py \
   skills/badge-app-development/template/metadata.json \
   src/apps/greeter/
```

Then:

1. Edit `metadata.json` (`app_name`, `author`, `info`).
2. Add `icon.bmp` — **exactly 128x76**:
   `magick art.png -resize 128x76! -colors 16 BMP3:src/apps/greeter/icon.bmp`
3. Only if the app writes files, rename `boot.json.example` to `boot.json`.
4. Copy the folder to `/apps/` on CIRCUITPY, unmount, reset.

`code.py` is a working asyncio-event app: static text on e-ink, a live counter on
the LCD, S4 to count, S7 to quit. Read the comments — they mark the spots that
bite people.
