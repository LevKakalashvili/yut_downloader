#!/usr/bin/env python3
"""
YouTube downloader driven by a JSON config.
Requires: yt-dlp, ffmpeg
Usage: python ytdownloader.py path/to/config.json
"""
from __future__ import annotations

import json
import sys
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yt_dlp
except ImportError as e:
    print("Missing dependency: yt-dlp. Install with: pip install yt-dlp")
    raise

log = logging.getLogger("ytdl")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def _progress_hook(d):
    if d.get("status") == "downloading":
        p = d.get("_percent_str") or ""
        s = d.get("_speed_str") or ""
        eta = d.get("eta")
        log.info(f"downloading {p.strip()} @ {s.strip()} ETA {eta}s")
    elif d.get("status") == "finished":
        log.info("download finished; post-processing...")

def build_ydl_opts(item: Dict[str, Any], cfg: Dict[str, Any]):
    out_dir = Path(cfg.get("output_dir", "downloads")).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename_template = item.get("filename_template") or cfg.get("filename_template") or "%(title)s.%(ext)s"
    outtmpl = str(out_dir / filename_template)

    proxy = item.get("proxy") or cfg.get("proxy")
    ffmpeg_location = item.get("ffmpeg_location") or cfg.get("ffmpeg_location")
    cookiefile = item.get("cookies") or cfg.get("cookies")

    # Defaults
    ydl_opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": False,
        "progress_hooks": [_progress_hook],
        "retries": 10,
        "concurrent_fragment_downloads": item.get("concurrent_fragments", cfg.get("concurrent_fragments", 5)),
    }

    if proxy:
        ydl_opts["proxy"] = proxy
    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    # Decide what to fetch
    requested_type = (item.get("type") or "video").lower()  # "video" | "audio"
    convert_to_audio = item.get("convert_to_audio", cfg.get("convert_to_audio", False))

    video_format = item.get("video_format", cfg.get("video_format", "mp4"))
    quality = item.get("quality", cfg.get("quality", "best"))  # "best", "bestvideo+bestaudio/best", etc.

    audio_format = item.get("audio_format", cfg.get("audio_format", "mp3"))
    audio_bitrate = str(item.get("audio_bitrate", cfg.get("audio_bitrate", 192)))  # kbps as string

    # Format selection
    if requested_type == "audio":
        # Download best audio and extract to desired codec
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": audio_bitrate,
            }
        ]
    else:
        # Video path
        if quality == "best":
            # Prefer best video+audio muxed; fallback to best
            ydl_opts["format"] = "bv*+ba/b"
        else:
            # Allow user to pass yt-dlp format selector directly (advanced)
            ydl_opts["format"] = quality

        # Ensure final extension if we need a particular container
        ydl_opts["merge_output_format"] = video_format

        if convert_to_audio:
            # Also extract separate audio file after video download
            pp = ydl_opts.setdefault("postprocessors", [])
            pp.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": audio_bitrate,
            })

    # Throttling / rate limit
    if "rate_limit" in cfg or "rate_limit" in item:
        ydl_opts["ratelimit"] = item.get("rate_limit", cfg.get("rate_limit"))

    # SponsorBlock / chapters removal options (optional)
    remove_sponsor_segments = item.get("remove_sponsor_segments", cfg.get("remove_sponsor_segments", False))
    if remove_sponsor_segments:
        ydl_opts["sponsorblock_mark"] = ["sponsor", "intro", "outro", "interaction", "selfpromo"]

    return ydl_opts

def download_item(item: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    url = item.get("url")
    if not url:
        raise ValueError("Every item must contain 'url'")
    ydl_opts = build_ydl_opts(item, cfg)
    log.info(f"Start: {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    log.info("Done.")

def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python ytdownloader.py path/to/config.json")
        return 2
    config_path = Path(sys.argv[1]).expanduser()
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 2

    with config_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    items = cfg.get("items") or []
    if not items:
        print("Config must contain non-empty 'items' list.")
        return 2

    for idx, item in enumerate(items, 1):
        try:
            log.info(f"[{idx}/{len(items)}] processing")
            download_item(item, cfg)
        except Exception as e:
            log.error(f"Failed item {idx}: {e}", exc_info=True)
            if cfg.get("stop_on_error", False):
                return 1
            # else continue

    log.info("All tasks finished.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
