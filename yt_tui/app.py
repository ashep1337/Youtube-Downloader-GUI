#!/usr/bin/env python3
"""TUI for yt-dlp and ffmpeg."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import subprocess
from pathlib import Path

from rich.text import Text

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Click, MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    ProgressBar,
    RadioButton,
    RadioSet,
    Rule,
    Static,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _format_label(f: dict) -> str:
    """Build a human-readable label for a yt-dlp format dict."""
    fmt_id = f.get("format_id", "?")
    ext = f.get("ext", "?")
    res = f.get("resolution", "audio only")
    fps = f.get("fps")
    vcodec = f.get("vcodec", "none")
    acodec = f.get("acodec", "none")
    filesize = f.get("filesize") or f.get("filesize_approx")
    size_str = _human_size(filesize) if filesize else "unknown size"

    has_video = vcodec != "none"
    has_audio = acodec != "none"
    kind = "V+A" if has_video and has_audio else ("V" if has_video else "A")

    fps_str = f" {fps}fps" if fps else ""
    return f"[{kind}] {res}{fps_str} / {ext} / {size_str}  (id:{fmt_id})"


def _parse_duration(text: str) -> int | None:
    """Parse duration string like '1:30', '90', '1:30:00' into seconds."""
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _seconds_to_hms(s: int | float) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{sec:02d}"
    return f"{m:d}:{sec:02d}"


def _seconds_to_hms_full(s: int | float) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# Timeline bar widget
# ---------------------------------------------------------------------------

MARKER_SNAP_DISTANCE = 2


class TimelineBar(Widget, can_focus=True):
    """Interactive timeline bar with draggable cut markers."""

    BINDINGS = [
        Binding("left", "nudge(-1)", "Left", show=False),
        Binding("right", "nudge(1)", "Right", show=False),
        Binding("shift+left", "nudge(-5)", "Left x5", show=False),
        Binding("shift+right", "nudge(5)", "Right x5", show=False),
        Binding("space", "toggle_marker", "Add/Remove marker"),
    ]

    DEFAULT_CSS = """
    TimelineBar {
        height: 5;
        width: 1fr;
        padding: 0 1;
    }
    TimelineBar:focus {
        border: tall $accent;
    }
    """

    class MarkersChanged(Message):
        def __init__(self, markers: list[float]) -> None:
            super().__init__()
            self.markers = markers

    duration: reactive[float] = reactive(0.0)
    cursor_seconds: reactive[float] = reactive(0.0)

    def __init__(self, duration: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.duration = duration
        self.cursor_seconds = 0.0
        self._markers: list[float] = []
        self._dragging_idx: int | None = None

    @property
    def markers(self) -> list[float]:
        return sorted(self._markers)

    @markers.setter
    def markers(self, value: list[float]) -> None:
        self._markers = sorted(value)
        self.refresh()
        self.post_message(self.MarkersChanged(self.markers))

    @property
    def _bar_width(self) -> int:
        w = self.content_size.width
        return max(10, w)

    def _seconds_to_col(self, seconds: float) -> int:
        if self.duration <= 0:
            return 0
        frac = seconds / self.duration
        return int(round(frac * (self._bar_width - 1)))

    def _col_to_seconds(self, col: int) -> float:
        if self._bar_width <= 1:
            return 0.0
        frac = col / (self._bar_width - 1)
        return max(0.0, min(self.duration, frac * self.duration))

    def _find_nearest_marker(self, col: int) -> int | None:
        best_idx = None
        best_dist = MARKER_SNAP_DISTANCE + 1
        for i, m in enumerate(self._markers):
            mcol = self._seconds_to_col(m)
            dist = abs(mcol - col)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        return best_idx

    def render(self) -> Text:
        w = self._bar_width
        if self.duration <= 0 or w < 10:
            return Text("No duration available")

        marker_cols = {self._seconds_to_col(m) for m in self._markers}
        cursor_col = self._seconds_to_col(self.cursor_seconds)

        row1 = [" "] * w
        row1[min(cursor_col, w - 1)] = "\u25bd"

        row2 = ["\u2500"] * w
        row2[0] = "\u251c"
        row2[-1] = "\u2524"
        for mc in marker_cols:
            if 0 < mc < w - 1:
                row2[mc] = "\u2503"

        row3 = [" "] * w
        for mc in marker_cols:
            if 0 <= mc < w:
                row3[mc] = "\u25b2"

        start_label = _seconds_to_hms(0)
        end_label = _seconds_to_hms(self.duration)
        cursor_label = f"cursor: {_seconds_to_hms(self.cursor_seconds)}"
        row4_str = start_label + " " * max(1, w - len(start_label) - len(end_label)) + end_label

        text = Text()
        for i, ch in enumerate("".join(row1)):
            if ch == "\u25bd":
                text.append(ch, style="bold cyan")
            else:
                text.append(ch)
        text.append("\n")

        for i, ch in enumerate("".join(row2)):
            if ch == "\u2503":
                text.append(ch, style="bold yellow")
            else:
                text.append(ch, style="dim")
        text.append("\n")

        for i, ch in enumerate("".join(row3)):
            if ch == "\u25b2":
                text.append(ch, style="bold yellow")
            else:
                text.append(ch)
        text.append("\n")

        text.append(row4_str, style="dim")
        text.append("  ")
        text.append(cursor_label, style="bold cyan")

        return text

    def action_nudge(self, delta: int) -> None:
        if self.duration <= 0:
            return
        step = self.duration / (self._bar_width - 1) if self._bar_width > 1 else 1
        self.cursor_seconds = max(0.0, min(self.duration, self.cursor_seconds + delta * step))
        self.refresh()

    def action_toggle_marker(self) -> None:
        if self.duration <= 0:
            return
        cursor_col = self._seconds_to_col(self.cursor_seconds)
        near_idx = self._find_nearest_marker(cursor_col)
        if near_idx is not None:
            self._markers.pop(near_idx)
        else:
            self._markers.append(self.cursor_seconds)
            self._markers.sort()
        self.refresh()
        self.post_message(self.MarkersChanged(self.markers))

    def on_click(self, event: Click) -> None:
        if self.duration <= 0:
            return
        col = max(0, min(event.x, self._bar_width - 1))
        self.cursor_seconds = self._col_to_seconds(col)
        self.refresh()

    def on_mouse_down(self, event: MouseDown) -> None:
        if self.duration <= 0:
            return
        col = max(0, min(event.x, self._bar_width - 1))
        near_idx = self._find_nearest_marker(col)
        if near_idx is not None:
            self._dragging_idx = near_idx
            self.capture_mouse()
            event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if self._dragging_idx is not None and self.duration > 0:
            col = max(0, min(event.x, self._bar_width - 1))
            new_seconds = self._col_to_seconds(col)
            self._markers[self._dragging_idx] = new_seconds
            self.cursor_seconds = new_seconds
            self.refresh()

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._dragging_idx is not None:
            self._dragging_idx = None
            self.release_mouse()
            self._markers.sort()
            self.refresh()
            self.post_message(self.MarkersChanged(self.markers))


# ---------------------------------------------------------------------------
# Screen 1: URL input
# ---------------------------------------------------------------------------

class URLScreen(Screen):
    CSS = """
    #url-container {
        align: center middle;
        width: 80;
        height: auto;
        padding: 2 4;
    }
    #url-input {
        width: 100%;
        margin: 1 0;
    }
    #url-error {
        color: red;
        margin: 0 0 1 0;
    }
    #fetch-btn {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="url-container"):
            yield Label("Enter a YouTube URL:")
            yield Input(placeholder="https://www.youtube.com/watch?v=...", id="url-input")
            yield Label("", id="url-error")
            yield Button("Fetch formats", variant="primary", id="fetch-btn")
        yield Footer()

    @on(Button.Pressed, "#fetch-btn")
    def on_fetch(self) -> None:
        self._do_fetch()

    @on(Input.Submitted, "#url-input")
    def on_submit(self) -> None:
        self._do_fetch()

    def _do_fetch(self) -> None:
        url = self.query_one("#url-input", Input).value.strip()
        if not url:
            self.query_one("#url-error", Label).update("Please enter a URL.")
            return
        self.query_one("#url-error", Label).update("")
        self.query_one("#fetch-btn", Button).disabled = True
        self.query_one("#fetch-btn", Button).label = "Fetching..."
        self._fetch_formats(url)

    @work(thread=True)
    def _fetch_formats(self, url: str) -> None:
        try:
            result = subprocess.run(
                ["yt-dlp", "-j", "--no-download", url],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                self.app.call_from_thread(self._show_error, result.stderr.strip())
                return
            info = json.loads(result.stdout)
            self.app.call_from_thread(self._on_formats_ready, url, info)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    def _show_error(self, msg: str) -> None:
        self.query_one("#url-error", Label).update(msg[:200])
        self.query_one("#fetch-btn", Button).disabled = False
        self.query_one("#fetch-btn", Button).label = "Fetch formats"

    def _on_formats_ready(self, url: str, info: dict) -> None:
        self.app.url = url
        self.app.video_info = info
        self.app.push_screen(OptionsScreen())


# ---------------------------------------------------------------------------
# Screen 2: Options (mode, quality, splitting)
# ---------------------------------------------------------------------------

class OptionsScreen(Screen):
    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    #options-scroll {
        padding: 1 4;
    }
    .section-title {
        text-style: bold;
        margin: 1 0 0 0;
    }
    #format-list {
        height: auto;
        max-height: 16;
        margin: 0 0 1 0;
    }
    #download-btn {
        margin: 2 0;
        width: 100%;
    }
    #timeline {
        margin: 1 0;
    }
    #marker-info {
        margin: 0 0 1 0;
    }
    #preset-row {
        height: 3;
        margin: 0 0 1 0;
    }
    #preset-row Button {
        margin: 0 1 0 0;
        min-width: 10;
    }
    """

    def compose(self) -> ComposeResult:
        info = self.app.video_info
        title = info.get("title", "Unknown")
        duration = info.get("duration") or 0
        dur_str = _seconds_to_hms(int(duration)) if duration else "unknown"

        yield Header()
        with VerticalScroll(id="options-scroll"):
            yield Label(f"Title: {title}")
            yield Label(f"Duration: {dur_str}")
            yield Rule()

            # Mode selection
            yield Label("Download mode:", classes="section-title")
            with RadioSet(id="mode-radio"):
                yield RadioButton("Video + Audio", value=True, id="mode-video")
                yield RadioButton("Audio only", id="mode-audio")

            yield Rule()

            # Format / quality selection
            yield Label("Select format / quality:", classes="section-title")
            yield Label("(highlight a format and press Enter or click)", id="format-hint")

            formats = info.get("formats", [])
            self._video_formats = [
                f for f in formats
                if f.get("vcodec", "none") != "none"
            ]
            self._audio_formats = [
                f for f in formats
                if f.get("vcodec", "none") == "none" and f.get("acodec", "none") != "none"
            ]
            self._video_formats.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
            self._audio_formats.sort(key=lambda f: (f.get("abr") or f.get("tbr") or 0), reverse=True)

            all_fmts = self._video_formats + self._audio_formats
            self._all_formats = all_fmts

            items = []
            for f in all_fmts:
                items.append(ListItem(Label(_format_label(f))))

            yield ListView(*items, id="format-list")
            yield Checkbox("Use best auto quality instead", value=True, id="auto-best")

            yield Rule()

            # Split / cut section with timeline
            yield Label("Split / cut output:", classes="section-title")
            yield Checkbox("Enable splitting", id="split-check")

            yield Label("Click the bar to position cursor, Space to add/remove cut markers.")
            yield Label("Click and drag markers to reposition. Arrow keys for fine adjustment.")
            yield TimelineBar(duration=float(duration), id="timeline", disabled=True)
            yield Label("No cut markers set.", id="marker-info")

            # Preset buttons
            yield Label("Quick presets:", classes="section-title")
            with Horizontal(id="preset-row"):
                yield Button("Half (1/2)", id="preset-half", disabled=True)
                yield Button("Thirds (1/3)", id="preset-thirds", disabled=True)
                yield Button("Quarters (1/4)", id="preset-quarters", disabled=True)
                yield Button("Clear all", id="preset-clear", disabled=True, variant="error")

            yield Rule()

            # Output directory
            yield Label("Output directory:", classes="section-title")
            yield Input(value=str(Path.home() / "Downloads"), id="output-dir")

            yield Button("Download", variant="primary", id="download-btn")
        yield Footer()

    @on(Checkbox.Changed, "#split-check")
    def toggle_split(self, event: Checkbox.Changed) -> None:
        enabled = event.value
        self.query_one("#timeline", TimelineBar).disabled = not enabled
        self.query_one("#preset-half", Button).disabled = not enabled
        self.query_one("#preset-thirds", Button).disabled = not enabled
        self.query_one("#preset-quarters", Button).disabled = not enabled
        self.query_one("#preset-clear", Button).disabled = not enabled

    @on(Checkbox.Changed, "#auto-best")
    def toggle_auto(self, event: Checkbox.Changed) -> None:
        self.query_one("#format-list", ListView).disabled = event.value

    @on(TimelineBar.MarkersChanged)
    def on_markers_changed(self, event: TimelineBar.MarkersChanged) -> None:
        self._update_marker_info(event.markers)

    def _update_marker_info(self, markers: list[float]) -> None:
        duration = self.app.video_info.get("duration") or 0
        if not markers:
            self.query_one("#marker-info", Label).update("No cut markers set.")
            return

        points = [0.0] + markers + [float(duration)]
        parts = []
        for i in range(len(points) - 1):
            start = points[i]
            end = points[i + 1]
            length = end - start
            parts.append(f"  Part {i+1}: {_seconds_to_hms(start)} - {_seconds_to_hms(end)} ({_seconds_to_hms(length)})")

        cut_strs = [_seconds_to_hms(m) for m in markers]
        header = f"Cut points: {', '.join(cut_strs)}  |  {len(markers)+1} segments:"
        info_text = header + "\n" + "\n".join(parts)
        self.query_one("#marker-info", Label).update(info_text)

    # -- Preset buttons -----------------------------------------------------

    def _set_preset_markers(self, divisions: int) -> None:
        duration = self.app.video_info.get("duration") or 0
        if duration <= 0:
            return
        timeline = self.query_one("#timeline", TimelineBar)
        expected = [duration * i / divisions for i in range(1, divisions)]
        current = timeline.markers
        if len(current) == len(expected) and all(
            abs(a - b) < 2 for a, b in zip(current, expected)
        ):
            timeline.markers = []
        else:
            timeline.markers = expected

    @on(Button.Pressed, "#preset-half")
    def on_preset_half(self) -> None:
        self._set_preset_markers(2)

    @on(Button.Pressed, "#preset-thirds")
    def on_preset_thirds(self) -> None:
        self._set_preset_markers(3)

    @on(Button.Pressed, "#preset-quarters")
    def on_preset_quarters(self) -> None:
        self._set_preset_markers(4)

    @on(Button.Pressed, "#preset-clear")
    def on_preset_clear(self) -> None:
        self.query_one("#timeline", TimelineBar).markers = []

    # -- Download -----------------------------------------------------------

    @on(Button.Pressed, "#download-btn")
    def start_download(self) -> None:
        mode_set = self.query_one("#mode-radio", RadioSet)
        audio_only = mode_set.pressed_index == 1

        auto_best = self.query_one("#auto-best", Checkbox).value

        selected_format = None
        if not auto_best:
            lv = self.query_one("#format-list", ListView)
            idx = lv.index
            if idx is not None and 0 <= idx < len(self._all_formats):
                selected_format = self._all_formats[idx]["format_id"]

        split_enabled = self.query_one("#split-check", Checkbox).value
        cut_points = []
        if split_enabled:
            cut_points = self.query_one("#timeline", TimelineBar).markers

        output_dir = self.query_one("#output-dir", Input).value.strip()
        if not output_dir:
            self.notify("Output directory required", severity="error")
            return

        self.app.download_opts = {
            "audio_only": audio_only,
            "auto_best": auto_best,
            "format_id": selected_format,
            "split": split_enabled and len(cut_points) > 0,
            "cut_points": cut_points,
            "output_dir": output_dir,
        }
        self.app.push_screen(DownloadScreen())

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Screen 3: Download + progress
# ---------------------------------------------------------------------------

class DownloadScreen(Screen):
    CSS = """
    #dl-container {
        padding: 2 4;
    }
    #dl-log {
        height: 1fr;
        margin: 1 0;
        border: round $surface;
    }
    #dl-progress {
        margin: 1 0;
    }
    #done-btn {
        margin: 1 0;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dl-container"):
            yield Label("Downloading...", id="dl-status")
            yield ProgressBar(total=100, show_eta=False, id="dl-progress")
            yield Log(id="dl-log", auto_scroll=True)
            yield Button("Done - New download", variant="primary", id="done-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._run_download()

    @work(thread=True)
    def _run_download(self) -> None:
        opts = self.app.download_opts
        url = self.app.url
        info = self.app.video_info
        output_dir = opts["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        title = re.sub(r'[<>:"/\\|?*]', '_', info.get("title", "video"))
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        set_progress = lambda v: self.app.call_from_thread(self._set_progress, v)
        set_status = lambda s: self.app.call_from_thread(self._set_status, s)

        # Build yt-dlp command
        cmd = ["yt-dlp", "--newline", "--progress"]

        if opts["audio_only"]:
            if opts["auto_best"] or not opts["format_id"]:
                cmd += ["-f", "bestaudio"]
            else:
                cmd += ["-f", opts["format_id"]]
            cmd += ["-x", "--audio-format", "mp3"]
            ext = "mp3"
        else:
            if opts["auto_best"] or not opts["format_id"]:
                cmd += ["-f", "bestvideo+bestaudio/best"]
            else:
                cmd += ["-f", f"{opts['format_id']}+bestaudio/best"]
            cmd += ["--merge-output-format", "mkv"]
            ext = "mkv"

        output_template = os.path.join(output_dir, f"{title}.%(ext)s")
        cmd += ["-o", output_template, url]

        log(f"Running: {' '.join(cmd)}\n")
        set_status("Downloading...")

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                log(line)
                m = re.search(r'(\d+\.?\d*)%', line)
                if m:
                    set_progress(float(m.group(1)))
            proc.wait()

            if proc.returncode != 0:
                log(f"\nyt-dlp exited with code {proc.returncode}")
                set_status("Download failed!")
                self.app.call_from_thread(self._enable_done)
                return
        except Exception as e:
            log(f"\nError: {e}")
            set_status("Download failed!")
            self.app.call_from_thread(self._enable_done)
            return

        set_progress(100)

        # Find the downloaded file
        downloaded = self._find_downloaded_file(output_dir, title, ext)
        if not downloaded:
            log(f"\nCould not find downloaded file in {output_dir}")
            set_status("Download complete but file not found for splitting.")
            self.app.call_from_thread(self._enable_done)
            return

        log(f"\nDownloaded: {downloaded}")

        # Split if requested
        if opts["split"] and opts["cut_points"]:
            set_status("Splitting file...")
            set_progress(0)
            self._split_at_markers(downloaded, opts["cut_points"], log, set_progress, set_status)
        else:
            set_status("Done!")

        self.app.call_from_thread(self._enable_done)

    def _find_downloaded_file(self, output_dir: str, title: str, expected_ext: str) -> str | None:
        dirpath = Path(output_dir)
        candidates = []
        for f in dirpath.iterdir():
            if f.is_file() and f.stem.startswith(title[:20]):
                candidates.append(f)
        if not candidates:
            candidates = [f for f in dirpath.iterdir() if f.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return str(candidates[0])

    def _split_at_markers(
        self,
        filepath: str,
        cut_points: list[float],
        log,
        set_progress,
        set_status,
    ) -> None:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                capture_output=True, text=True, timeout=30,
            )
            total_duration = float(result.stdout.strip())
        except Exception:
            log("Could not determine file duration.")
            total_duration = None

        p = Path(filepath)
        stem = p.stem
        ext = p.suffix
        out_dir = str(p.parent)

        points = [0.0] + sorted(cut_points)
        if total_duration:
            points.append(total_duration)
        else:
            points.append(points[-1] + 3600)

        num_segments = len(points) - 1
        log(f"\nSplitting into {num_segments} segments at cut points: {', '.join(_seconds_to_hms(c) for c in cut_points)}\n")

        created_parts = []
        for i in range(num_segments):
            start = points[i]
            end = points[i + 1]
            part_name = f"{stem}_part{i+1:03d}{ext}"
            part_path = os.path.join(out_dir, part_name)

            cmd = [
                "ffmpeg",
                "-i", filepath,
                "-ss", _seconds_to_hms_full(start),
                "-to", _seconds_to_hms_full(end),
                "-c", "copy",
                "-y",
                part_path,
            ]

            log(f"Segment {i+1}/{num_segments}: {_seconds_to_hms(start)} -> {_seconds_to_hms(end)}")
            log(f"  {' '.join(cmd)}")

            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        log(f"  {line}")
                proc.wait()

                if proc.returncode != 0:
                    log(f"  ffmpeg exited with code {proc.returncode}")
                else:
                    created_parts.append(part_name)
            except Exception as e:
                log(f"  Error: {e}")

            progress = ((i + 1) / num_segments) * 100
            set_progress(progress)

        log(f"\nCreated {len(created_parts)} segments:")
        for part in created_parts:
            log(f"  {part}")

        # Delete the original file now that segments exist
        if created_parts:
            try:
                os.remove(filepath)
                log(f"\nRemoved original file: {Path(filepath).name}")
            except OSError as e:
                log(f"\nCould not remove original file: {e}")

        set_status(f"Done! {len(created_parts)} segments created.")

    def _log(self, msg: str) -> None:
        self.query_one("#dl-log", Log).write_line(msg)

    def _set_progress(self, value: float) -> None:
        self.query_one("#dl-progress", ProgressBar).progress = value

    def _set_status(self, msg: str) -> None:
        self.query_one("#dl-status", Label).update(msg)

    def _enable_done(self) -> None:
        self.query_one("#done-btn", Button).disabled = False

    @on(Button.Pressed, "#done-btn")
    def on_done(self) -> None:
        self.app.switch_screen(URLScreen())


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class YtTuiApp(App):
    TITLE = "yt-tui"
    SUB_TITLE = "YouTube Downloader TUI"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]
    CSS = """
    Screen {
        background: $surface;
    }
    """

    url: str = ""
    video_info: dict = {}
    download_opts: dict = {}

    def on_mount(self) -> None:
        self.push_screen(URLScreen())


def main():
    app = YtTuiApp()
    app.run()


if __name__ == "__main__":
    main()
