#!/usr/bin/env python3
"""Take screenshots of the TUI for the README."""

import asyncio
from yt_tui.app import YtTuiApp, OptionsScreen, URLScreen

MOCK_INFO = {
    "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
    "duration": 213,
    "formats": [
        {"format_id": "313", "ext": "webm", "resolution": "3840x2160", "fps": 30, "vcodec": "vp9", "acodec": "none", "filesize": 450_000_000, "height": 2160, "tbr": 15000},
        {"format_id": "271", "ext": "webm", "resolution": "2560x1440", "fps": 30, "vcodec": "vp9", "acodec": "none", "filesize": 220_000_000, "height": 1440, "tbr": 8000},
        {"format_id": "137", "ext": "mp4", "resolution": "1920x1080", "fps": 30, "vcodec": "avc1", "acodec": "none", "filesize": 120_000_000, "height": 1080, "tbr": 4500},
        {"format_id": "136", "ext": "mp4", "resolution": "1280x720", "fps": 30, "vcodec": "avc1", "acodec": "none", "filesize": 60_000_000, "height": 720, "tbr": 2500},
        {"format_id": "135", "ext": "mp4", "resolution": "854x480", "fps": 30, "vcodec": "avc1", "acodec": "none", "filesize": 30_000_000, "height": 480, "tbr": 1200},
        {"format_id": "140", "ext": "m4a", "resolution": "audio only", "vcodec": "none", "acodec": "mp4a", "filesize": 3_400_000, "abr": 129, "tbr": 129},
        {"format_id": "251", "ext": "webm", "resolution": "audio only", "vcodec": "none", "acodec": "opus", "filesize": 3_200_000, "abr": 128, "tbr": 128},
        {"format_id": "139", "ext": "m4a", "resolution": "audio only", "vcodec": "none", "acodec": "mp4a", "filesize": 1_200_000, "abr": 48, "tbr": 48},
    ],
}


class ScreenshotURLApp(YtTuiApp):
    """Captures the URL screen."""
    def on_mount(self) -> None:
        self.push_screen(URLScreen())
        self.set_timer(1.0, self._snap)

    async def _snap(self) -> None:
        self.save_screenshot("screenshots/url.svg")
        self.exit()


class _NoAutoMount(YtTuiApp):
    """Base that skips the default URLScreen push."""
    def on_mount(self) -> None:
        pass  # override parent


class ScreenshotOptionsApp(_NoAutoMount):
    """Captures the options screen."""
    def on_mount(self) -> None:
        self.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.video_info = MOCK_INFO
        self.push_screen(OptionsScreen())
        self.set_timer(1.0, self._snap)

    async def _snap(self) -> None:
        self.save_screenshot("screenshots/options.svg")
        self.exit()


class ScreenshotSplitApp(_NoAutoMount):
    """Captures the options screen with splitting enabled."""
    def on_mount(self) -> None:
        self.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.video_info = MOCK_INFO
        self._opts_screen = OptionsScreen()
        self.push_screen(self._opts_screen)
        self.set_timer(1.5, self._enable_split)

    async def _enable_split(self) -> None:
        from textual.widgets import Checkbox
        from yt_tui.app import TimelineBar
        screen = self._opts_screen
        chk = screen.query_one("#split-check", Checkbox)
        chk.value = True
        await asyncio.sleep(0.5)
        timeline = screen.query_one("#timeline", TimelineBar)
        timeline.markers = [MOCK_INFO["duration"] / 2]
        await asyncio.sleep(0.5)
        self.save_screenshot("screenshots/options_split.svg")
        self.exit()


if __name__ == "__main__":
    import os
    os.makedirs("screenshots", exist_ok=True)

    print("Capturing URL screen...")
    ScreenshotURLApp().run(headless=True, size=(100, 35))

    print("Capturing options screen...")
    ScreenshotOptionsApp().run(headless=True, size=(100, 40))

    print("Capturing split screen...")
    ScreenshotSplitApp().run(headless=True, size=(100, 40))
