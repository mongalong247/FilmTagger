# Packaging & releasing FilmTagger

This folder holds everything needed to build distributable FilmTagger
archives for Windows, macOS, and Linux. Read this before touching the
build. Ported from ImageImporter's packaging setup (this project's sibling
app) -- the two apps share `paths.py` and `exiftool_manager.py`'s design,
so the packaging story is the same for both.

## The short version

- Push a tag (`v1.4.0`) → GitHub Actions (`.github/workflows/release.yml`)
  builds all three platforms natively and attaches zipped/tarballed archives
  to a **draft** GitHub Release for you to review and publish.
- Or trigger the workflow manually from the Actions tab to test packaging
  changes without cutting a real release.
- Distribution format is a **portable archive** (zip / tar.gz), not an
  installer wizard — unzip it and run the exe/app inside. No admin rights,
  no install/uninstall flow to maintain.

## Why not a single-file .exe, and what "_internal" was about

Earlier attempts (on ImageImporter, before this pattern existed) used
`--onefile` or added `resources/` (the bundled ExifTool binary) to
PyInstaller via `--add-data`. Both are wrong for this app, for different
reasons:

- **`--onefile`** re-extracts the whole app to a fresh temp folder on
  every launch. That's actively broken here because `exiftool_manager.py`
  keeps a small pool of long-running, `-stay_open` ExifTool processes
  pointed at a specific on-disk path for the life of the app run — that
  path needs to be stable, not a temp folder.
- **Adding `resources/` via `datas=`** means PyInstaller 6+ nests it
  inside its internal libs folder (`_internal/` on Windows/Linux onedir
  builds) instead of leaving it next to the actual `.exe`. But
  `paths.py` deliberately resolves persistent storage (the bundled
  ExifTool, saved camera/lens/film-stock presets) as
  `os.path.dirname(sys.executable) / "resources"` — the folder containing
  the *executable*, not PyInstaller's internal libs folder. The two
  disagree, so the bundled ExifTool would silently go missing at runtime.

**The fix**: build in `onedir` mode (`packaging/FilmTagger.spec`), and
never hand `resources/` to PyInstaller at all. Instead,
`packaging/copy_resources.py` runs as an explicit step *after* the
PyInstaller build and copies `resources/` directly into the same folder as
the built executable. This works regardless of what PyInstaller's internal
layout looks like in any given version, because it isn't relying on
PyInstaller's data-file placement at all — it's just a plain file copy to
a path we compute ourselves.

## Platform differences

| Platform | Bundled ExifTool? | Why |
|---|---|---|
| Windows | Yes — `resources/exiftool.exe` + `resources/exiftool_files/` | No universal system package manager; bundling avoids a manual install step for most users. |
| macOS | No | `exiftool_manager.py`'s fallback chain checks system PATH first, then bundled. Ships no `resources/exiftool*` at all — if ExifTool isn't found, the app still launches (metadata tagging just disables itself) and shows a Homebrew install hint. |
| Linux | No | Same fallback chain; shows distro-appropriate `apt`/`dnf`/`pacman` install hints. |

This matches how `exiftool_manager.py` already works — no code changes
were needed to support mac/Linux builds without a bundled binary, it
already degrades gracefully (`ensure_exiftool_available()` never treats a
missing ExifTool as fatal).

## Sourcing ExifTool for Windows builds

The Windows ExifTool zip is **vendored directly in the repo**, at
`vendor/exiftool-<VERSION>_64.zip` — it is committed, not gitignored. The
release workflow's Windows job just unzips it locally into `resources/`
before running PyInstaller; it does not fetch anything over the network.

This is deliberate, not a shortcut: SourceForge (where ExifTool's Windows
build is hosted) returns a flat `403 Forbidden` to GitHub Actions' runner
IP ranges as anti-abuse policy against cloud/datacenter IPs (confirmed
directly on ImageImporter's workflow, which hit it with both
`Invoke-WebRequest` and `curl.exe`, with retries and different user
agents). None of that reliably works around a deliberate IP-range block,
so the network fetch is left out of CI entirely -- same zip FilmTagger and
ImageImporter both pin (`13.59`), vendored once from a normal residential
connection.

`resources/exiftool.exe` and `resources/exiftool_files/` themselves stay
gitignored (see `.gitignore`) — they're the *unzipped, build-time-generated*
copy, not the source. Only the zip in `vendor/` is committed.

Likewise, `resources/presets/*.json` (Ian's own dev camera/lens/film-stock
data) are excluded from the copied build output by
`packaging/copy_resources.py` — a fresh install should start with an empty
preset store, not ship someone else's specific gear as if it were sample
content. They stay tracked in the repo itself (source-controlled dev data),
just not copied into `dist/`.

**To update the vendored ExifTool version** (e.g. when ExifTool ships a new
release and you bump `PINNED_BUNDLED_VERSION` in `exiftool_manager.py` to
match):

1. On a normal (non-cloud/CI) internet connection, download
   `exiftool-<version>_64.zip` from https://exiftool.org (links to
   SourceForge; a home/office connection isn't blocked, only CI/cloud IP
   ranges are).
2. Delete the old file in `vendor/` and add the new one, keeping the exact
   `exiftool-<version>_64.zip` naming.
3. Update `EXIFTOOL_VERSION` in `.github/workflows/release.yml` to match.
4. Update `PINNED_BUNDLED_VERSION` in `exiftool_manager.py` to match, if you
   haven't already.
5. Commit all three changes together (and consider doing the same for
   ImageImporter's vendored copy, so both apps ship the same pinned
   version).

**The version in `vendor/`, `EXIFTOOL_VERSION` in the workflow, and
`PINNED_BUNDLED_VERSION` in `exiftool_manager.py` must always agree** — the
app's own status text/UI reports the constant as "what's bundled", so a
mismatch means the app is lying about its own contents.

## Building locally (one platform at a time)

PyInstaller does not cross-compile — build on the OS you're targeting.

```bash
pip install -r requirements.txt -r requirements-build.txt

# Windows only, first: unzip vendor/exiftool-<version>_64.zip into resources/
# the same way the workflow does (exiftool(-k).exe -> resources/exiftool.exe,
# exiftool_files/ -> resources/exiftool_files/)

pyinstaller packaging/FilmTagger.spec --noconfirm --clean
python packaging/copy_resources.py
```

Output:
- Windows/Linux: `dist/FilmTagger/` (onedir folder — `FilmTagger.exe` or
  `FilmTagger` plus `_internal/` plus `resources/`, all siblings)
- macOS: `dist/FilmTagger.app`

Zip/tar that folder up and it's the same portable archive the release
workflow produces.

## App icon

Unlike ImageImporter, FilmTagger doesn't ship a custom app icon yet --
`packaging/FilmTagger.spec` builds with `icon=None` on every platform.
When one's ready, follow ImageImporter's pattern: add
`assets/app_icon.ico`, wire it into the `EXE()`/`BUNDLE()` calls in the
spec, add a `datas=[(os.path.join(REPO_ROOT, "assets"), "assets")]` entry,
and add the "Generate macOS app icon" step (via
`packaging/make_macos_icon.py`, ported from ImageImporter if/when needed)
to the release workflow.

## A note on where user data lands

`paths.py` stores everything persistent (bundled ExifTool, saved presets,
`QSettings`) next to the executable. On Windows/Linux that's the top-level
unzipped folder; on macOS it's inside the `.app` bundle
(`Contents/MacOS/resources/`), which is normal/expected for a self-contained
mac app. One implication worth knowing: if a user unzips the portable
archive into a location their OS locks down (e.g. `C:\Program Files` on
Windows without running as admin), saving a preset or first-run ExifTool
resolution could fail on write. Worth telling users in the README/release
notes to unzip somewhere in their own user space (Desktop, Documents,
`~/Applications`, etc.) rather than a system-protected folder.
