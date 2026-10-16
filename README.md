# ttwatch — public TikTok channel tracker

A tool that runs on your own machine: enter a list of TikTok channels and it reads each channel's followers, likes and videos, stores the history in SQLite, draws charts, compares channels and alerts you to large changes. Python (FastAPI + Playwright), a local web UI that needs no npm, and a system tray icon. The UI language is Vietnamese.

Download the prebuilt Windows version from [Releases](https://github.com/huuhungn/ttwatch/releases) (unzip and run `ttwatch.exe`). User guide: `docs/user-guide.md`; change history: `CHANGELOG.md`.

The data folder and environment variable names (`TheoDoiKenhTiktok_data`, `TDK_DATA_DIR`) are kept from earlier versions so that previously scanned data is not lost.

## Run

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python app.py
```

The page opens at `http://127.0.0.1:8765/` (the first free port in 8765–8774). When run from source, data is stored next to `app.py`; in the packaged build it is stored in `TheoDoiKenhTiktok_data` next to the exe (or in `%LOCALAPPDATA%\TheoDoiKenhTiktok` if that folder is not writable). Set `TDK_DATA_DIR` to point to a different folder. `NO_OPEN=1` skips opening the browser and `NO_TRAY=1` hides the tray icon.

The tool only reads public TikTok pages, using a browser on your machine. It does not send data anywhere else. Private channels and captchas block reading; the tool reports an error instead of trying to bypass them.

## CI and releases

- `.github/workflows/ci.yml`: on every push and pull request, runs ruff, a JS syntax check and the full test suite (including the UI tests with Chrome) on Windows.
- `.github/workflows/release.yml`: pushing a `v*` tag (for example `git tag v0.1.0 && git push origin v0.1.0`) builds the exe, smoke-tests it (ping, home page, shutdown), zips it with a SHA256 file and creates a GitHub Release. A manual run from the Actions tab only creates an artifact.

On another machine, just download the zip from Releases, unzip it and run `ttwatch.exe`; data is stored in `TheoDoiKenhTiktok_data` next to the exe.

The exe is not code-signed, so Windows SmartScreen may show a warning the first time (choose *More info → Run anyway*). Compare the downloaded file with the accompanying `.sha256` file if you want to be sure.

Since 0.1.2, every release zip comes with a provenance attestation (GitHub Artifact Attestation, signed with Sigstore). It confirms that the file was built by this repository's `release.yml` workflow from the exact commit of the tag. Verify it with the [GitHub CLI](https://cli.github.com/):

```bash
gh attestation verify ttwatch-v0.1.2-win64.zip -R huuhungn/ttwatch
```

## Testing

```bash
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
TDK_DATA_DIR=$(mktemp -d) .venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check --select F,E9 .
```

`TDK_DATA_DIR` must point to an empty folder: the app refuses to start when two instances share one data folder. The UI tests (`tests/test_ui.py`) open a real browser (Chrome, Edge or Playwright's Chromium) with fake data, never call TikTok, and skip themselves if the machine has no browser. Screenshots are saved to `docs/screens/`.

## Building the exe

```powershell
powershell -File build.ps1      # produces dist\ttwatch\ttwatch.exe (~150 MB for the whole folder)
```

Requires `uv` on PATH; the script installs PyInstaller into `.venv` by itself. `build/`, `dist/` and `*.spec` are already ignored. The exe uses the Edge/Chrome already installed on the machine. For code-signing a release, see `docs/code-signing.md`.

## Layout

| File | Role |
|---|---|
| `app.py` | FastAPI: API, static pages, file export, startup |
| `scraper.py` | Playwright, scan queue, retries, auto-refresh |
| `db.py` | SQLite, versioned migrations, backups |
| `insights.py` | history, overview, analysis, comparison, alerts, saved views |
| `instance_lock.py` | single-instance lock on the data folder |
| `tray.py`, `paths.py` | system tray, data paths |
| `static/` | the UI (no npm needed): `main.js` channel table, `panels.js` the newer screens, `charts.js` SVG charts |

## License

MIT, see `LICENSE`. Third-party libraries (FastAPI, Playwright, pystray, Pillow, openpyxl, ...) keep their own licenses. The tool only reads public data; you are responsible for complying with TikTok's terms when you use it.
