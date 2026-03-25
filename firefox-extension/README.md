# YouTube Downloader – Firefox Extension

A Firefox extension that adds a download button to YouTube video pages. Supports format selection, audio extraction, and video splitting/cutting via a local Python backend powered by yt-dlp and ffmpeg.

## Requirements

- Firefox 109+
- Python 3
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [ffmpeg](https://ffmpeg.org/) (for merging, audio extraction, and splitting)

## Setup

### 1. Start the backend server

```bash
nohup python3 /home/user/path/Youtube-Downloader-GUI/firefox-extension/backend/server.py > /tmp/ytdl-backend.log 2>&1 &
```

The server runs on `http://127.0.0.1:5123`. To stop it:

```bash
pkill -f "server.py"
```

### 2. Install the extension

1. Open `about:debugging` in Firefox
2. Click **"This Firefox"**
3. Click **"Load Temporary Add-on"**
4. Select `manifest.json` from this directory

## Usage

1. Navigate to any YouTube video
2. Click the red download button in the top-right corner to open the panel
3. The panel shows backend connection status and the video title/duration
4. Click **Fetch Formats** to pull all available formats via yt-dlp
5. Choose your options:
   - **Download Mode** – Video+Audio or Audio Only
   - **Format/Quality** – pick a specific format or use auto-best
   - **Split/Cut** – enable splitting, then double-click the timeline to add cut markers
6. Set the output directory (defaults to `~/Downloads`)
7. Click **Download**

### Timeline controls

| Action                   | Effect                       |
| ------------------------ | ---------------------------- |
| Click                    | Move cursor                  |
| Double-click             | Add a cut marker             |
| Drag marker              | Reposition it                |
| Right-click marker       | Remove it                    |
| Half / Thirds / Quarters | Preset evenly-spaced markers |
| Clear                    | Remove all markers           |

## File structure

```
firefox-extension/
├── manifest.json      # Extension manifest (MV2)
├── content.js         # Content script – injects button and panel on YouTube
├── background.js      # Background script – proxies fetch requests to backend
├── panel.css          # Dark-themed styles for button and panel
├── icons/
│   ├── icon-48.svg
│   └── icon-96.svg
└── backend/
    └── server.py      # Local Python HTTP server wrapping yt-dlp & ffmpeg
```

## API endpoints (backend)

| Method | Path             | Description                       |
| ------ | ---------------- | --------------------------------- |
| GET    | `/`              | Status check                      |
| GET    | `/health`        | Health check                      |
| POST   | `/formats`       | Fetch available formats for a URL |
| POST   | `/download`      | Start a download task             |
| GET    | `/progress/<id>` | Poll download progress            |
