#!/usr/bin/env python3
"""
Local backend server for the YouTube Downloader Firefox extension.

Provides HTTP API endpoints:
  GET  /health           – check if server is alive
  POST /formats          – fetch available formats for a URL
  POST /download         – start a download task
  GET  /progress/<id>    – poll download progress

Requires: yt-dlp, ffmpeg (in PATH)
Run:  python server.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HOST = "127.0.0.1"
PORT = 5123

# ── Task store ────────────────────────────────────────────────────────────

tasks: dict[str, dict] = {}
tasks_lock = threading.Lock()


def new_task() -> str:
    task_id = uuid.uuid4().hex[:12]
    with tasks_lock:
        tasks[task_id] = {
            "status": "Starting...",
            "percent": 0,
            "log": "",
            "done": False,
        }
    return task_id


def update_task(task_id: str, **kwargs):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id].update(kwargs)


def append_log(task_id: str, line: str):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["log"] += line + "\n"


def get_task(task_id: str) -> dict | None:
    with tasks_lock:
        return tasks.get(task_id, {}).copy() if task_id in tasks else None


# ── Helpers ───────────────────────────────────────────────────────────────

def seconds_to_hms(s: int | float) -> str:
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ── Download worker ──────────────────────────────────────────────────────

def download_worker(task_id: str, opts: dict):
    try:
        _do_download(task_id, opts)
    except Exception as e:
        append_log(task_id, f"\nFatal error: {e}")
        update_task(task_id, status="Download failed!", done=True)


def _do_download(task_id: str, opts: dict):
    url = opts["url"]
    audio_only = opts.get("audio_only", False)
    auto_best = opts.get("auto_best", True)
    format_id = opts.get("format_id")
    do_split = opts.get("split", False)
    cut_points = opts.get("cut_points", [])
    output_dir = opts.get("output_dir", "~/Downloads")

    # Expand ~ in path
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Get title for filename
    update_task(task_id, status="Fetching video info...")
    try:
        info_result = subprocess.run(
            ["yt-dlp", "-j", "--no-download", url],
            capture_output=True, text=True, timeout=60,
        )
        info = json.loads(info_result.stdout)
        title = re.sub(r'[<>:"/\\|?*]', '_', info.get("title", "video"))
    except Exception:
        title = "video"

    # Build yt-dlp command
    cmd = ["yt-dlp", "--newline", "--progress"]

    if audio_only:
        if auto_best or not format_id:
            cmd += ["-f", "bestaudio"]
        else:
            cmd += ["-f", format_id]
        cmd += ["-x", "--audio-format", "mp3"]
        ext = "mp3"
    else:
        if auto_best or not format_id:
            cmd += ["-f", "bestvideo+bestaudio/best"]
        else:
            cmd += ["-f", f"{format_id}+bestaudio/best"]
        cmd += ["--merge-output-format", "mkv"]
        ext = "mkv"

    output_template = os.path.join(output_dir, f"{title}.%(ext)s")
    cmd += ["-o", output_template, url]

    append_log(task_id, f"$ {' '.join(cmd)}\n")
    update_task(task_id, status="Downloading...")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            append_log(task_id, line)
            m = re.search(r"(\d+\.?\d*)%", line)
            if m:
                update_task(task_id, percent=float(m.group(1)))
        proc.wait()

        if proc.returncode != 0:
            append_log(task_id, f"\nyt-dlp exited with code {proc.returncode}")
            update_task(task_id, status="Download failed!", done=True)
            return
    except Exception as e:
        append_log(task_id, f"\nError: {e}")
        update_task(task_id, status="Download failed!", done=True)
        return

    update_task(task_id, percent=100)

    # Find downloaded file
    downloaded = _find_downloaded_file(output_dir, title)
    if not downloaded:
        append_log(task_id, f"\nCould not find downloaded file in {output_dir}")
        update_task(task_id, status="Download complete but file not found.", done=True)
        return

    append_log(task_id, f"\nDownloaded: {downloaded}")

    # Split if requested
    if do_split and cut_points:
        update_task(task_id, status="Splitting file...", percent=0)
        _split_at_markers(task_id, downloaded, cut_points)
    else:
        update_task(task_id, status="Done!", done=True)


def _find_downloaded_file(output_dir: str, title: str) -> str | None:
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


def _split_at_markers(task_id: str, filepath: str, cut_points: list[float]):
    # Get file duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True, timeout=30,
        )
        total_duration = float(result.stdout.strip())
    except Exception:
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
    append_log(task_id, f"\nSplitting into {num_segments} segments...\n")

    created_parts = []
    for i in range(num_segments):
        start = points[i]
        end = points[i + 1]
        part_name = f"{stem}_part{i + 1:03d}{ext}"
        part_path = os.path.join(out_dir, part_name)

        cmd = [
            "ffmpeg", "-i", filepath,
            "-ss", seconds_to_hms(start),
            "-to", seconds_to_hms(end),
            "-c", "copy", "-y",
            part_path,
        ]

        append_log(task_id, f"Segment {i + 1}/{num_segments}: {seconds_to_hms(start)} -> {seconds_to_hms(end)}")

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    append_log(task_id, f"  {line}")
            proc.wait()

            if proc.returncode != 0:
                append_log(task_id, f"  ffmpeg exited with code {proc.returncode}")
            else:
                created_parts.append(part_name)
        except Exception as e:
            append_log(task_id, f"  Error: {e}")

        progress = ((i + 1) / num_segments) * 100
        update_task(task_id, percent=progress)

    append_log(task_id, f"\nCreated {len(created_parts)} segments:")
    for part in created_parts:
        append_log(task_id, f"  {part}")

    # Remove original
    if created_parts:
        try:
            os.remove(filepath)
            append_log(task_id, f"\nRemoved original file: {Path(filepath).name}")
        except OSError as e:
            append_log(task_id, f"\nCould not remove original: {e}")

    update_task(task_id, status=f"Done! {len(created_parts)} segments created.", done=True)


# ── HTTP Handler ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self._json_response(200, {"status": "YouTube Downloader backend is running"})
            return

        if self.path == "/health":
            self._json_response(200, {"ok": True})
            return

        if self.path.startswith("/progress/"):
            task_id = self.path.split("/progress/", 1)[1]
            task = get_task(task_id)
            if task is None:
                self._json_response(404, {"error": "Unknown task"})
            else:
                self._json_response(200, task)
            return

        self._json_response(404, {"error": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if self.path == "/formats":
            try:
                data = json.loads(body)
                url = data.get("url", "")
                if not url:
                    self._json_response(400, {"error": "Missing url"})
                    return
                result = subprocess.run(
                    ["yt-dlp", "-j", "--no-download", url],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode != 0:
                    self._json_response(500, {"error": result.stderr.strip()[:500]})
                    return
                info = json.loads(result.stdout)
                self._json_response(200, info)
            except json.JSONDecodeError:
                self._json_response(400, {"error": "Invalid JSON"})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
            return

        if self.path == "/download":
            try:
                opts = json.loads(body)
                if not opts.get("url"):
                    self._json_response(400, {"error": "Missing url"})
                    return
                task_id = new_task()
                thread = threading.Thread(target=download_worker, args=(task_id, opts), daemon=True)
                thread.start()
                self._json_response(200, {"task_id": task_id})
            except json.JSONDecodeError:
                self._json_response(400, {"error": "Invalid JSON"})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
            return

        self._json_response(404, {"error": "Not found"})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"YouTube Downloader backend running on http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
