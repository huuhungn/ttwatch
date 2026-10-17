# Changelog

## Unreleased

### Added
- **Setup.exe.** Releases now include `ttwatch-v<version>-Setup.exe` next to the zip: a per-user installer (no administrator rights) built with Inno Setup that installs into `%LOCALAPPDATA%\Programs\ttwatch`, adds a Start Menu entry, an optional Desktop icon and an *Installed apps* entry, and offers to start the tool at the end. Installing a newer Setup over an older copy closes the running tool, replaces the program files and keeps `TheoDoiKenhTiktok_data`; uninstalling stops the tool, removes the program files and the *Start with Windows* entry, and leaves your data folder alone. The in-app self-update still uses the zip, so an installed copy updates itself too.
- The exe and installer have their own icon (`packaging/app.ico`).
- A release gate (`packaging/assert_clean_package.ps1`) fails the build when the packaged folder contains a database, browser profile, log or tool state.
- `installer-smoke.yml` and the release workflow install the Setup on a clean runner, install a newer one over a running older copy and uninstall it, checking that user data survives each step.

### Changed
- `release.yml` packages with `build.ps1`, so the local and CI builds use the same PyInstaller options; the Setup is covered by the build provenance attestation and has its own `.sha256`.

## 0.3.0 — 2026-10-17

### Added
- **Start with Windows.** A *Tự chạy cùng Windows* checkbox in *Cài đặt* (off by default) adds one per-user entry to `HKCU\...\Run`, so no administrator rights and no scheduled task are needed. Windows starts the tool with `--background`: it comes up in the tray and keeps scanning and alerting, without opening the browser page. The entry is removed when you untick the box and is repaired at the next start if the install folder was moved. If you disabled it in Task Manager → Startup apps, the setting says so and ticking the box again turns it back on; the automatic repair never overrides that choice. Only the exe can do this; from source the box is disabled with the reason (`GET`/`POST /api/autostart`, setting `autostart`).
- **Scan pacing.** The tool rests a random few seconds between channels instead of a fixed 1.5 seconds, and scroll and video-page waits vary a little too. When TikTok pushes back (a captcha, an empty video list for a channel that has videos, an unreadable page, a timeout that survives the retries, or TikTok stopping mid-scan) the tool rests 45 seconds (2 minutes after a captcha), doubling with every further trouble in a row up to 15 minutes at every pace, and returns to the normal pace after the first clean scan (troubles more than 30 minutes apart count as separate incidents, and a captcha you solve yourself does not slow the queue down). The bar under the header shows the countdown with a *Quét tiếp ngay* button (`POST /api/worker/resume`) to skip it.
- A *Nhịp quét* setting (`scan_pace`): normal (default), slow, or fast (the old fixed pause, no backing off).

### Changed
- `/api/channels` and the other worker statuses carry a `pause` field (`null` when nothing is waiting out trouble).
- Settings also store `scan_pace` and `autostart`; `POST /api/worker/resume` and `GET`/`POST /api/autostart` are new.
- `--background` on the command line (what the Windows startup entry passes) starts the tool without opening the page, like `NO_OPEN=1`.

## 0.2.0 — 2026-10-16

### Added
- **Self-update.** The exe checks the latest GitHub Release a short while after start and every 6 hours, and offers the new version in a bar under the header (*Cập nhật ngay* / *Để sau* / *Bỏ qua bản này*). By default it also installs a new version by itself when no scan is running. The package is downloaded over HTTPS, checked against its SHA256 and unpacked next to the app; the app then restarts into the new version, the old program files are deleted, and your data folder is never touched. If anything goes wrong while swapping files, the old version is put back. Turn the check or the automatic install off in *Cài đặt*, or use the tray item *Kiểm tra cập nhật*.
- The version is shown in *Giới thiệu* and in `/api/ping`; `version.py` is the single source, and `release.yml` refuses a tag that does not match it.

### Changed
- Settings now also store `update_check`, `update_auto`, `update_skip` and `update_failed`.

## 0.1.2 — 2026-10-16

### Added
- Every release zip has a provenance attestation (GitHub Artifact Attestation, Sigstore): verify it with `gh attestation verify <zip> -R huuhungn/ttwatch`.
- An Authenticode signing step using SignPath in `release.yml`, enabled automatically when the repo has SignPath configured (see `docs/code-signing.md`); skipped when it is not configured.

## 0.1.1 — 2026-10-16

### Added
- MIT license (`LICENSE`, also included in the release zip).
- When TikTok asks for a captcha, the tool brings the browser window to the front, shows a notice in the tray and waits up to 3 minutes for you to solve it; once solved, the tool resumes scanning and hides the window again. If you give up, it waits 10 minutes before showing the window again.

## 0.1.0 — 2026-10-16

### Added
- **Overview** and **Alerts** tabs; a channel detail panel with history charts and analysis; comparison of 2–6 channels.
- A 30-day trend column; saved views; a Ctrl+K command palette; keyboard shortcut help.
- Import channels from txt/csv (with group and note); export history as CSV; download a backup.
- Alerts when followers change beyond a threshold and when a new video appears, with a tray notification balloon.
- Typed auto-update (quick / 10-video scan) and quiet hours.
- Videos page: summary cards, analysis, highlighting of outperforming videos, CSV export.
- Undo when deleting a channel; a banner when channels were interrupted mid-scan; suggested fixes for common errors.
- Manual light/dark theme, compact table, clear focus, respects reduced motion.
- Group chips (right-click to rename or ungroup), sticky #/username columns, row selection arrows, keyboard-navigable tabs, comparison by percentage change.
- Text colors meet WCAG AA in both themes (measured by tests running in a browser).
- Documentation: `docs/user-guide.md`. The project's logo, name and links were replaced with this repo's; the exe was renamed to `ttwatch.exe`.
- GitHub Actions: `ci.yml` (ruff, JS syntax, the full test suite including the UI, on Windows) and `release.yml` (build the exe, smoke-test it, zip with SHA256, create a Release when a `v*` tag is pushed).

### Changed
- The SQLite schema is versioned (`PRAGMA user_version`) with ordered migrations.
- The database is backed up automatically every day and before migrating (7 copies kept).
- SQLite connections are closed right after use (previously they held the file lock until garbage collection).
- Existing data opens as before; the old API keeps its shape and only gains new keys.

### Fixed
- A channel was treated as failed when TikTok navigated away while data was being read; transient network errors are now retried; ER and growth figures accumulate correctly.

### Testing
- From 24 to 103 tests, including UI tests that drive a real browser with fake data and a performance test on 300 channels × 200 videos × 60 snapshots.
