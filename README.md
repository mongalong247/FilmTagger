# FilmTagger

Adds camera, film stock, lens, aperture and shutter speed metadata to
scanned or digitally-photographed 35mm film rolls, via presets you manage
in-app.

## Running from source

```bash
pip install -r requirements.txt
python app.py
```

ExifTool is required to actually write metadata (loading and reviewing a
roll works without it). The app looks for it in this order: a custom path
set in Settings, a system-wide install on `PATH`, then a bundled copy next
to the app (Windows release builds only -- see `packaging/README.md`).

## Building a distributable release

See `packaging/README.md` for the full PyInstaller + GitHub Actions release
pipeline (ported from this project's sibling app, ImageImporter).
