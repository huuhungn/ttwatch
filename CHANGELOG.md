# Changelog

## 0.6.0 — 2026-10-25

### Added
- **Standout video alert.** After an update, a video posted in the last 30 days that reaches 3 times the channel's median views (needs at least 5 videos) creates a ★ alert with its views and how many times the median it is, and shows in the tray like the other alerts. Each video alerts once, on the update that takes it over the bar. Set the multiple in *Cài đặt* (`alert_viral_x`, 0 = off).
- **Hashtags and video length in the channel detail.** *Hashtag hay dùng* lists the tags found in the descriptions of at least 2 videos with their median views against the channel's; a tag opens the video list filtered by it (`/videos?u=<user>&q=<text>` now prefills the search). *View trung vị theo thời lượng* compares median views by video length. Both come from data the tool already stores, so no rescan is needed. `GET /api/channels/{username}/insights` gains `hashtags` and `durations`.

### Changed
- *Cảnh báo* groups alerts by day (*Hôm nay*, *Hôm qua*, then the date), filters them by kind with chips, colors each kind's icon, and marks an alert read when you click it.
- *Cài đặt* is split into titled groups (scanning, auto-update, alerts, startup and updates, appearance, data) laid out in two columns on wide windows, and *Lưu* stays visible at the bottom while the dialog scrolls.
- *Tăng nhanh nhất* in *Tổng quan* also shows each channel's current followers or views and the change in percent; the gainers in `GET /api/overview` gain `value` and `pct` (`null` when the starting value is 0).

### Fixed
- The compare chart's axis shows percentages in *% thay đổi* mode instead of bare numbers.
- On narrow windows the box for pasting channels no longer collapses and cuts off its second example line.

## 0.5.0 — 2026-10-18

### Added
- **Scan monitor.** The bar under the header now says what the scan is doing and how far it has got: the current step (opening the channel, waiting for the video list, scrolling, waiting for you to solve a captcha, retrying), how long the channel has been running, how many channels of the batch are done, an estimate of the time left (from the second finished channel on) and how many failed.
- **Stuck scans are flagged.** When the running channel shows no sign of life for 2 minutes, the spinner turns into a warning that the scan may be stuck and what to do.
- **Finished runs are reported.** When the queue empties the bar keeps a summary (*Quét xong N kênh trong …*, with the number of failed channels) until you close it, and the tray shows a notice for runs of two or more channels or with failures (not during quiet hours).

### Changed
- `GET /api/channels` and the other worker statuses gain `batch` and `last`; `current` gains `step`, `elapsed`, `idle` and `stalled`.
- The installer smoke test creates the `Run` registry key when a fresh runner profile lacks it (the first release run for 0.4.0 failed on that) and waits up to 2 minutes for the app to start.

## 0.4.0 — 2026-10-17

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
