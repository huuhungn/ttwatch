# User guide

The app's interface is in Vietnamese. This guide quotes each label exactly as it appears, in backticks, with the English meaning in parentheses the first time it is used.

## Quick start

1. Paste channel links, video links or `@username` into the box at the top (one channel per line, or separated by commas or spaces). Choose a scan type and click `Thêm kênh` (Add channel), or press Ctrl+Enter.
2. The tool fetches channel and video information with a browser on your machine; progress is shown in the top-right corner.
3. Each update stores one history snapshot. You need at least two snapshots before growth figures and charts appear.

## Screens

### Channels
The main table. Right-click for a menu: quick update, scan videos by count or by days, assign a group, add a note, copy figures, export to Excel, delete.

- `Cập nhật nhanh` (Quick update, F5): channel info and the latest videos, without scrolling.
- `Quét video` (Scan videos): scrolls the channel to collect more videos: all of them, the latest N videos, the last N days, or a date range.
- The `Xu hướng 30 ngày` (30-day trend) column draws the follower movement; click its header to sort by growth.
- `Chế độ xem` (Views) saves the search box, group, visible columns and sort order so you can recall them later.
- Deleting a channel (`Xóa`) shows an `Hoàn tác` (Undo) button in the notification for 8 seconds; after that the channel is deleted for good, together with all its videos and history.

### Overview (`Tổng quan`)
Total cards, charts of total followers and views, a `Tăng nhanh nhất` (Fastest growing) table over 24 hours / 7 / 30 days, channels not updated for a long time (over 3 days), failed channels, and standout videos of the last 30 days.
A newly tracked channel is marked `mới theo dõi` (newly tracked): its growth is measured from its first snapshot, not over the full period.

### Channel detail
Select a channel and press **Space** (or right-click → `Biểu đồ và phân tích`, Charts and analysis).

- History charts of followers, likes, views and video count over 7/30/90 days or all time.
- **Median views** (`View trung vị`) is the level that half of the videos exceed; it is less skewed by one viral video than the average is.
- **Outperformers** (`Vượt trội`): videos with at least 2 times the median views (needs at least 5 videos).
- **Best posting times** (`Giờ đăng hiệu quả`): a weekday × hour heatmap colored by average views. The slot named is the one with the highest average views among slots with at least 2 videos.

### Compare
Select 2–6 channels (Ctrl+click), then right-click → `So sánh các kênh đã chọn` (Compare the selected channels).

### Alerts (`Cảnh báo`)
Generated after every successful update, from the second one onwards:
- followers changed by at least the percentage threshold (default 5%, adjustable in `Cài đặt` (Settings); 0 = off);
- the channel has a new video between two updates.

A red dot on the tab shows the number of unread alerts. The system tray also shows a notification balloon.

### Video list
Double-click a channel (or press Enter). It has summary cards, a `Phân tích` (Analysis) section (collapsed by default) computed over exactly the videos currently filtered, a ★ marker for outperforming videos, and Excel or CSV export.

## Import, export, backup

- **Import**: a `.txt` file (one channel or link per line) or a `.csv` file with the header row `username,group,note`. Existing channels keep their group when the group column is empty.
- **Export**: an Excel file of the channel list (25 columns), Excel/CSV of videos, and a CSV of one channel's history (in the channel detail).
- **Backup**: Settings → `Tải bản sao lưu` (Download backup) downloads a consistent `.db` copy. The tool also backs up automatically every day and before upgrading the data schema, into the `backups/` folder next to the data (7 copies kept).
- **Restore**: close the tool, copy a file from `backups/` to `data.db` (first rename the old `data.db`, `data.db-wal` and `data.db-shm`), then start it again.

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+K | Command palette: find channels, switch screens, run actions |
| ? | Shortcut help |
| Enter | Open the video list |
| Space | Channel detail |
| F5 | Quick update |
| Del | Delete (with undo) |
| Ctrl+A / Ctrl+C | Select all / copy usernames |
| 1 2 3 | Channels / Overview / Alerts |
| Esc | Close the detail panel, clear the selection |

## Settings

- `Hiện cửa sổ trình duyệt` (Show the browser window): always show the tool's browser window. It is not required for solving captchas: when TikTok asks for verification, the tool brings the window to the front, shows a notice in the tray and waits up to 3 minutes; once you solve it, the tool resumes scanning and remembers the verified session.
- **Auto-update**: interval in minutes, type (quick or a 10-video scan) and quiet hours (may span midnight).
- **Scan pace** (`Nhịp quét`): *Bình thường* (default) rests a random few seconds between channels; *Chậm* rests longer, better when you follow many channels; *Nhanh* keeps the old fixed 1.5-second pause and never slows down. Whatever the pace, when TikTok shows a captcha, returns an empty video list for a channel that has videos, or a page cannot be read, the tool rests 45 seconds (2 minutes after a captcha), doubling for every further trouble in a row up to 15 minutes at every pace, and goes back to the normal pace after the first clean scan. Troubles more than 30 minutes apart start again from the first step, and a captcha you solve yourself does not slow the queue down. The bar under the header shows the countdown with a *Quét tiếp ngay* button to skip the wait.
- **Start with Windows** (`Tự chạy cùng Windows`, off by default): the tool starts by itself when you sign in to Windows, quietly in the tray (no browser page), so auto-update and alerts keep working without you opening anything; open the page from the tray icon when you want to look. It adds one entry for your user only (no administrator rights). Untick it to remove the entry. If Windows shows the entry as disabled (Task Manager → Startup apps), the setting tells you; ticking the box and saving turns it on again. Only the exe supports this, not `python app.py`.
- **Alerts**: on/off, follower threshold, new videos.
- **Appearance**: light/dark/follow the system, compact table.
- **Updates**: the tool looks for a new version on GitHub by itself. When one exists a bar appears at the top: *Cập nhật ngay* downloads, installs and restarts the tool (takes a minute or two; your data is kept and the old version is removed); *Để sau* hides the bar until you reload the page; *Bỏ qua bản này* stops reminders for that version. By default a new version is also installed automatically when no scan is running; untick *Tự cài bản mới khi tool đang rảnh* to decide yourself, or untick *Tự kiểm tra bản mới trên GitHub* to turn the check off. *Kiểm tra bản mới ngay* and the tray item *Kiểm tra cập nhật* check on demand.

## Troubleshooting

| Message | What to do |
|---|---|
| Verification required (captcha) | The browser window appears by itself: solve the captcha within 3 minutes and the tool resumes scanning. If time runs out, the tool reports an error and only shows the window again after 10 minutes; rescan when you are present. |
| Channel does not exist or is locked | Check the username. |
| Interrupted | The tool was closed during a scan; click `Quét lại các kênh này` (Rescan these channels) in the yellow bar. |
| Browser profile is in use | Close the other browser window or tool that uses the same data folder. |
| Network error, timeout | The tool retries up to 3 times automatically; if it still fails, try again later. |
| `TikTok ngừng trả thêm` (TikTok stopped returning more) / 0 videos fetched | TikTok throttles rapid scanning (seen after several scans in a row within a few minutes, even 3-video scans). Channel info can still be fetched. How to recognize it: TikTok still returns HTTP 200 for the video list but the content is empty, with no captcha. The tool now rests by itself (see *Scan pace* in Settings), so a large queue slows down instead of making it worse; you can still wait and rescan (it has lasted over 30 minutes on one IP after about 8 consecutive scans); nothing else is needed. Scanning a channel with a very large number of videos often stops early (476/1512 was seen), and the tool does not delete old videos in this case. |
