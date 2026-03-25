# yt-tui

A terminal user interface for downloading YouTube videos and audio using [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

## Screenshots

### URL Input
<img width="722" height="436" alt="image" src="https://github.com/user-attachments/assets/b28991c7-9d36-4247-b2bb-39ed12b39ab8" />


### Format & Quality Selection
<img width="965" height="1378" alt="image" src="https://github.com/user-attachments/assets/3407b111-8dd6-4571-accb-665cf1e61e12" />


## Features

- **Download video + audio** or **extract audio only** (MP3)
- **Browse all available formats** — resolution, codec, file size — or use auto-best quality
- **Visual timeline bar** for splitting files at precise points:
  - Click to position the cursor, press Space to place/remove cut markers
  - Click and drag existing markers for fine-grained adjustment
  - Arrow keys to nudge the cursor (Shift+Arrow for 5x speed)
- **Quick split presets** — half, thirds, quarters — toggle on/off
- **Precise ffmpeg splitting** at your exact marker positions
- **Auto-cleanup** — original file is removed after successful splitting
- **Live progress** bar and log output during download and splitting

## Requirements

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [ffmpeg](https://ffmpeg.org/) (for splitting and audio extraction)

### Install dependencies

```bash
# Arch Linux
sudo pacman -S yt-dlp ffmpeg python

# Ubuntu / Debian
sudo apt install yt-dlp ffmpeg python3

# macOS
brew install yt-dlp ffmpeg python
```

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/Youtube-Downloader-GUI.git
cd Youtube-Downloader-GUI
pip install -e .
```

## Usage

```bash
# Run directly
python3 -m yt_tui.app

# Or if installed
yt-tui
```

### Workflow

1. **Paste a YouTube URL** and press Enter to fetch available formats
2. **Choose download mode** — Video + Audio or Audio Only
3. **Select quality** — pick a specific format from the list or use auto-best
4. **Optionally enable splitting** — use the timeline bar to place cut markers, or use presets (1/2, 1/3, 1/4)
5. **Set output directory** and hit Download
6. Watch the progress bar and log as it downloads and splits

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `Left` / `Right` | Move timeline cursor |
| `Shift+Left` / `Shift+Right` | Move cursor 5x faster |
| `Space` | Add/remove cut marker at cursor |
| `Escape` | Go back |
| `q` / `Ctrl+C` | Quit |

## License

MIT
