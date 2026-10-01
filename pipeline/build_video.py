"""Orchestrator for video chunk rendering, joining, and audio muxing."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
import requests
from PIL import Image

from pipeline import edit, qc_enforcement, stock

ROOT = Path(__file__).resolve().parent.parent
ASSET_CACHE = ROOT / "work" / "asset_cache"
ASSET_CACHE.mkdir(parents=True, exist_ok=True)


def _run_ffmpeg_safe(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    """Run an ffmpeg/ffprobe command with output redirected to disk to avoid PIPE deadlocks."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False) as logf:
        log_path = logf.name
    try:
        with open(log_path, "wb") as out:
            proc = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            output = f.read()
        return proc.returncode, output
    finally:
        try:
            os.unlink(log_path)
        except Exception:
            pass


def _get_ffmpeg_bin() -> str:
    """Return path to ffmpeg binary, trying PATH first then fallback."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    fallback = Path(
        r"D:\antigravity test\faceless-studio\tools\media\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
    )
    if fallback.exists():
        return str(fallback)
    return "ffmpeg"


def _is_valid_image(path: Path) -> bool:
    """Check a downloaded/cached file is actually decodable image data, not a corrupt/error page."""
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def _is_valid_video(path: Path) -> bool:
    """Check a video has a positive duration and a decodable tail."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        probe = subprocess.run(
            [
                edit._get_ffprobe_bin(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=20,
        )
        if probe.returncode != 0 or float(probe.stdout.strip()) <= 0:
            return False
        decode = subprocess.run(
            [
                edit._get_ffmpeg_bin(),
                "-nostdin",
                "-v",
                "error",
                "-sseof",
                "-2",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        return decode.returncode == 0 and not decode.stderr
    except Exception:
        return False


def download_asset(url: str, is_video: bool = False) -> Path | None:
    """Download an asset URL into ASSET_CACHE using cache-by-URL-hash pattern."""
    if not url:
        return None
    try:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        ext = Path(url.split("?")[0]).suffix
        if not ext or len(ext) > 5:
            ext = ".mp4" if is_video else ".jpg"
        cached_path = ASSET_CACHE / f"{url_hash}{ext}"
        is_video_ext = cached_path.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi", ".webm")
        needs_download = not cached_path.exists() or cached_path.stat().st_size == 0
        if not needs_download and is_video_ext and not _is_valid_video(cached_path):
            print(f"  build_video: cached video asset for '{url}' is corrupt, re-downloading")
            needs_download = True
        if not needs_download and not is_video_ext and not _is_valid_image(cached_path):
            print(f"  build_video: cached asset for '{url}' is corrupt, re-downloading")
            needs_download = True
        if needs_download:
            last_err = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, timeout=20, stream=True)
                    resp.raise_for_status()
                    bytes_written = 0
                    with open(cached_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                            bytes_written += len(chunk)
                    content_length = resp.headers.get("Content-Length")
                    if content_length is not None and bytes_written != int(content_length):
                        raise ValueError(
                            f"incomplete download: wrote {bytes_written} bytes, expected {content_length}"
                        )
                    if is_video_ext and not _is_valid_video(cached_path):
                        raise ValueError("downloaded video failed validation")
                    last_err = None
                    break
                except Exception as e:
                    cached_path.unlink(missing_ok=True)
                    last_err = e
                    time.sleep(2 * (attempt + 1))
            if last_err is not None:
                print(f"  build_video: download failed for URL '{url}' after 3 attempts: {last_err}")
                return None
            if not is_video_ext and not _is_valid_image(cached_path):
                print(f"  build_video: downloaded asset for '{url}' failed validation (corrupt/not an image)")
                cached_path.unlink(missing_ok=True)
                return None
        return cached_path
    except Exception as e:
        print(f"  build_video: download failed for URL '{url}': {e}")
        return None


def render_chunk(beat: dict, out_path: str) -> str:
    """Render a single video chunk from a media plan beat using edit filter builders."""
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    duration = float(beat.get("duration", 5.0))
    if duration < 5.0:
        raise ValueError(
            f"Clip duration {duration:.3f}s is below the hard 5.0s minimum; regenerate the media plan"
        )
    url = beat.get("url")
    local_path = beat.get("local_path")

    asset_file = None
    if local_path and Path(local_path).exists():
        asset_file = Path(local_path)
    elif url:
        asset_file = download_asset(url, is_video=False)

    if not asset_file or not asset_file.exists() or asset_file.stat().st_size == 0:
        placeholder = ASSET_CACHE / "placeholder.jpg"
        if not placeholder.exists():
            img = Image.new("RGB", (1920, 1080), color=(20, 20, 20))
            img.save(placeholder)
        asset_file = placeholder

    ffmpeg_bin = _get_ffmpeg_bin()
    kb_filter = edit.ken_burns_filter(duration)
    grade_filter = edit.documentary_grade_filter()

    is_video = asset_file.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi", ".webm")
    if is_video:
        start_offset = float(beat.get("start_offset", beat.get("ss", 0.0)))
        src_duration = edit._get_duration(str(asset_file))
        needs_loop = (src_duration - start_offset) < duration
        if needs_loop:
            start_offset = 0.0
            needs_loop = src_duration < duration

        input_flags = ["-nostdin", "-y"]
        if needs_loop:
            input_flags.extend(["-stream_loop", "-1"])
        elif start_offset > 0:
            input_flags.extend(["-ss", f"{start_offset:.3f}"])
        else:
            input_flags.extend(["-ss", "0"])

        vf = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=25,{grade_filter}"
        cmd = [
            ffmpeg_bin,
            *input_flags,
            "-i",
            str(asset_file),
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-t",
            f"{duration:.3f}",
            str(out_p),
        ]
    else:
        img_w, img_h = 1920, 1080
        try:
            with Image.open(asset_file) as im:
                img_w, img_h = im.size
        except Exception:
            pass

        post_filter = edit.postcard_filter(img_w, img_h, duration=duration)
        if post_filter is not None:
            vf = f"{post_filter},{grade_filter}"
        else:
            vf = f"{kb_filter},{grade_filter}"

        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-loop",
            "1",
            "-i",
            str(asset_file),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-t",
            f"{duration:.3f}",
            str(out_p),
        ]

    try:
        returncode, output = _run_ffmpeg_safe(cmd, timeout=300)
        if returncode != 0:
            raise RuntimeError(f"FFmpeg error: {output}")
        output_duration = edit._get_duration(str(out_p))
        if output_duration < duration - 0.25:
            raise RuntimeError(
                f"Rendered chunk is too short: {output_duration:.3f}s; expected at least {duration - 0.25:.3f}s"
            )
    except Exception as e:
        raise RuntimeError(
            f"render_chunk stage failed for query '{beat.get('query', '')}' at {out_path}: {e}"
        ) from e

    return str(out_p)


def _swap_in_broll_fallback(beat: dict, idx: int, used_broll_urls: set) -> bool:
    """Replace a beat's asset with a guaranteed-valid, not-yet-used crime-broll clip."""
    current_url = str(beat.get("url") or "")
    blocked = set(used_broll_urls)
    if current_url:
        blocked.add(current_url)
    res = stock.atmospheric_broll(idx, blocked)
    if res and res.get("url"):
        beat.pop("local_path", None)
        beat["url"] = res["url"]
        beat["query"] = res.get("query", beat.get("query", ""))
        beat["rights_status"] = res.get("rights_status")
        beat["credit"] = res.get("credit", "Pexels/Pixabay")
        beat["asset_kind"] = "video"
        beat["asset_missing"] = False
        used_broll_urls.add(res["url"])
        return True
    return False


def render_all_chunks(resolved_plan: list[dict], out_dir: str | Path) -> list[str]:
    """Render all beats in resolved plan as video chunks with QC enforcement."""
    out_d = Path(out_dir)
    out_d.mkdir(parents=True, exist_ok=True)
    passed_chunks = []
    failed_chunks = []

    # Track every broll URL already in the plan so a render-time swap never duplicates one.
    used_broll_urls: set = {
        str(beat["url"])
        for beat in resolved_plan
        if beat.get("url") and str(beat.get("rights_status") or "").lower().startswith(("pexels", "pixabay"))
    }

    for idx, beat in enumerate(resolved_plan):
        chunk_path = out_d / f"chunk_{idx:04d}.mp4"
        try:
            render_chunk(beat, str(chunk_path))
            qc_res = qc_enforcement.check_chunk(str(chunk_path))
            if not qc_res.get("pass", False):
                print(
                    f"  render_all_chunks: chunk {idx} failed QC ({qc_res}), re-rendering with same asset..."
                )
                render_chunk(beat, str(chunk_path))
                qc_res2 = qc_enforcement.check_chunk(str(chunk_path))
                if not qc_res2.get("pass", False):
                    print(
                        f"  render_all_chunks: chunk {idx} failed QC again ({qc_res2}); "
                        f"swapping in crime-broll fallback asset..."
                    )
                    if _swap_in_broll_fallback(beat, idx, used_broll_urls):
                        render_chunk(beat, str(chunk_path))
                        qc_res3 = qc_enforcement.check_chunk(str(chunk_path))
                        if not qc_res3.get("pass", False):
                            failed_chunks.append((idx, str(chunk_path), qc_res3))
                            continue
                    else:
                        failed_chunks.append((idx, str(chunk_path), qc_res2))
                        continue
            passed_chunks.append(str(chunk_path))
        except Exception as e:
            failed_chunks.append((idx, str(chunk_path), str(e)))

    if failed_chunks:
        raise RuntimeError(f"render_all_chunks failed for beats: {failed_chunks}")

    return passed_chunks


def join_chunks(chunk_paths: list[str], out_path: str) -> str:
    """Concatenate chunk paths into a single video file using edit.crossfade_concat."""
    cmd = edit.crossfade_concat(chunk_paths, out_path)
    try:
        returncode, output = _run_ffmpeg_safe(cmd, timeout=600)
        if returncode != 0:
            raise RuntimeError(f"FFmpeg error: {output}")
    except Exception as e:
        raise RuntimeError(f"join_chunks stage failed for {out_path}: {e}") from e
    return out_path


def prepend_intro_card(
    intro_card_path: str, main_video_path: str, out_path: str, fade_dur: float = 0.4
) -> str:
    """Prepend a silent intro card with matched video/audio crossfades.

    The generic concat helper is intentionally not used here: its concat-demuxer output takes
    its stream layout from the first (video-only) intro file, which drops the main video's audio.
    A filtergraph instead creates stereo silence for the intro, crossfades that into the main
    audio, and re-encodes both streams so the output has clean, monotonic timestamps.
    """
    out_p = Path(out_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    intro_duration = edit._get_duration(intro_card_path)
    if intro_duration <= fade_dur:
        raise ValueError(
            f"Intro duration {intro_duration:.3f}s must exceed fade duration {fade_dur:.3f}s"
        )
    fade_offset = intro_duration - fade_dur
    ffmpeg_bin = _get_ffmpeg_bin()
    filter_complex = (
        "[0:v]fps=25,scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,settb=AVTB,setpts=PTS-STARTPTS[v0];"
        "[1:v]fps=25,scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,settb=AVTB,setpts=PTS-STARTPTS[v1];"
        f"[v0][v1]xfade=transition=fade:duration={fade_dur:.3f}:"
        f"offset={fade_offset:.3f},format=yuv420p[v];"
        f"[2:a]atrim=duration={intro_duration:.6f},asetpts=PTS-STARTPTS,"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
        "[1:a]aresample=48000,asetpts=PTS-STARTPTS,"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
        f"[a0][a1]acrossfade=d={fade_dur:.3f}:c1=tri:c2=tri[a]"
    )
    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-y",
        "-i",
        intro_card_path,
        "-i",
        main_video_path,
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "25",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out_p),
    ]
    try:
        returncode, output = _run_ffmpeg_safe(cmd, timeout=1800)
        if returncode != 0:
            raise RuntimeError(f"FFmpeg error: {output}")
    except Exception as e:
        raise RuntimeError(f"prepend_intro_card stage failed for {out_path}: {e}") from e
    return str(out_p)


def mux_audio(video_path: str, audio_path: str, out_path: str) -> str:
    """Mux video and audio streams together, re-encoding video to guarantee correct timestamps.

    NOTE: -c:v copy was tried first but is unsafe here — a concat-demuxer-produced video can
    carry subtle PTS irregularities that only surface when the stream is copied again rather
    than fully decoded/re-encoded, which was confirmed to silently truncate ~10s off a real
    749.6s render (video-only ffprobe showed correct length pre-mux, then reported ~10s shorter
    post-mux with -c:v copy). Re-encoding forces clean, monotonic timestamps. Duration is pinned
    explicitly to the narration audio's length (the authoritative source of truth for timing)
    rather than trusting -shortest alone.
    """
    ffmpeg_bin = _get_ffmpeg_bin()
    _, probe_out = _run_ffmpeg_safe(
        [edit._get_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        timeout=20,
    )
    try:
        audio_duration = float(probe_out.strip())
    except Exception:
        audio_duration = None

    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
    ]
    if audio_duration:
        cmd.extend(["-t", f"{audio_duration:.3f}"])
    else:
        cmd.append("-shortest")
    cmd.append(out_path)
    try:
        returncode, output = _run_ffmpeg_safe(cmd, timeout=600)
        if returncode != 0:
            raise RuntimeError(f"FFmpeg error: {output}")
    except Exception as e:
        raise RuntimeError(f"mux_audio stage failed for {out_path}: {e}") from e
    return out_path


def mux_audio_with_music(
    video_path: str,
    narration_path: str,
    music_sections: list[dict],
    total_duration: float,
    out_path: str,
) -> str:
    """Build ducked music bed under narration and mux onto video stream.

    Uses safe re-encode + explicit -map/-t pinning pattern from mux_audio.
    """
    out_p = Path(out_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix="_music_bed.wav", delete=False) as tmp_bed:
        bed_path = tmp_bed.name
    with tempfile.NamedTemporaryFile(suffix="_ducked_mix.wav", delete=False) as tmp_mix:
        mix_path = tmp_mix.name

    try:
        from pipeline import music
        music.build_music_bed(music_sections, total_duration, bed_path)
        music.duck_music_under_narration(bed_path, narration_path, mix_path)
        return mux_audio(video_path, mix_path, str(out_p))
    finally:
        for p in (bed_path, mix_path):
            try:
                os.unlink(p)
            except Exception:
                pass

