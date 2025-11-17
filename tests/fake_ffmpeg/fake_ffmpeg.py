#!/usr/bin/env python3
"""
Fake ffmpeg/ffprobe implementation for testing.

This script simulates ffmpeg and ffprobe behavior without actually encoding video.
It handles:
- ffprobe: Returns JSON probe data
- ffmpeg: Simulates encoding with progress reporting via TCP
- loudnorm: Returns fake loudnorm JSON for audio normalization
"""

import sys
import os
import json
import time
import socket
from pathlib import Path

# Default configuration (can be overridden by environment variables)
FAKE_DURATION = float(os.environ.get("FAKE_FFMPEG_DURATION", "10.0"))
FAKE_DELAY = float(os.environ.get("FAKE_FFMPEG_DELAY", "0.01"))  # Delay between progress updates
FAKE_EXIT_CODE = int(os.environ.get("FAKE_FFMPEG_EXIT_CODE", "0"))
FAKE_UPDATE_FREQ = float(os.environ.get("FAKE_FFMPEG_UPDATE_FREQ", "0.5"))  # Seconds of "video" per update


def get_probe_data(input_file):
    """Return fake ffprobe JSON data."""
    # Check if there's a custom fixture for this file
    fixture_path = os.environ.get("FAKE_FFMPEG_PROBE_FIXTURE")
    if fixture_path and os.path.exists(fixture_path):
        with open(fixture_path, 'r') as f:
            return json.load(f)

    # Default probe data for a simple video with Japanese audio and English subs
    return {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "duration": str(FAKE_DURATION)
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "channels": 2,
                "sample_rate": "48000",
                "tags": {
                    "language": "jpn"
                }
            },
            {
                "index": 2,
                "codec_name": "subrip",
                "codec_type": "subtitle",
                "tags": {
                    "language": "eng"
                },
                "disposition": {
                    "default": 1
                }
            }
        ],
        "format": {
            "filename": str(input_file),
            "format_name": "matroska,webm",
            "format_long_name": "Matroska / WebM",
            "duration": str(FAKE_DURATION),
            "size": "104857600",
            "bit_rate": "8388608"
        }
    }


def get_loudnorm_json():
    """Return fake loudnorm analysis JSON."""
    return {
        "input_i": "-16.5",
        "input_tp": "-1.2",
        "input_lra": "8.3",
        "input_thresh": "-27.0",
        "output_i": "-14.0",
        "output_tp": "-2.0",
        "output_lra": "7.0",
        "output_thresh": "-24.5",
        "normalization_type": "dynamic",
        "target_offset": "2.5"
    }


def send_progress(tcp_url, duration):
    """Send progress updates to TCP server."""
    # Parse TCP URL (format: tcp://host:port)
    if not tcp_url.startswith("tcp://"):
        return

    host_port = tcp_url[6:]  # Remove "tcp://"
    try:
        host, port = host_port.rsplit(":", 1)
        port = int(port)
    except ValueError:
        print(f"Invalid TCP URL: {tcp_url}", file=sys.stderr)
        return

    # Connect to progress server
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))

        # Send progress updates
        current_time = 0.0
        frame = 0

        while current_time < duration:
            time.sleep(FAKE_DELAY)
            current_time += FAKE_UPDATE_FREQ
            frame += int(24 * FAKE_UPDATE_FREQ)  # Assume ~24fps

            # Send progress in ffmpeg format
            out_time_ms = int(min(current_time, duration) * 1_000_000)
            progress_data = f"frame={frame}\nout_time_ms={out_time_ms}\nprogress=continue\n"
            sock.sendall(progress_data.encode())

        # Send final update
        final_time_ms = int(duration * 1_000_000)
        final_data = f"frame={frame}\nout_time_ms={final_time_ms}\nprogress=end\n"
        sock.sendall(final_data.encode())

        sock.close()
    except Exception as e:
        print(f"Error sending progress: {e}", file=sys.stderr)


def is_loudnorm_analysis(args):
    """Check if this is a loudnorm analysis pass."""
    # Loudnorm analysis has: -filter:a loudnorm with print_format=json and -f null
    args_str = " ".join(args)
    return "loudnorm" in args_str and "print_format=json" in args_str and "-f" in args and "null" in args


def main():
    args = sys.argv[1:]
    program_name = os.path.basename(sys.argv[0])

    # Check if we're being invoked as ffprobe
    if "ffprobe" in program_name:
        # ffprobe mode: return JSON probe data
        # Find the input file (last non-flag argument, or after -i)
        input_file = None
        for i, arg in enumerate(args):
            if arg == "-i" and i + 1 < len(args):
                input_file = args[i + 1]
                break

        if not input_file:
            # Last argument that doesn't start with -
            for arg in reversed(args):
                if not arg.startswith("-"):
                    input_file = arg
                    break

        probe_data = get_probe_data(input_file)
        print(json.dumps(probe_data, indent=2))
        sys.exit(0)

    # ffmpeg mode: simulate encoding
    # Parse arguments
    progress_url = None
    output_file = None
    input_file = None

    # Track flags that take arguments
    skip_next = False
    flag_with_args = {'-progress', '-i', '-map', '-filter:a', '-c:v', '-c:a', '-c',
                      '-vf', '-af', '-f', '-profile:v', '-preset', '-tune', '-crf',
                      '-maxrate', '-bufsize', '-b:v', '-b:a', '-ac', '-t', '-r', '-g',
                      '-keyint_min', '-force_key_frames:v', '-hls_time', '-hls_playlist_type',
                      '-hls_list_size', '-hls_base_url', '-hls_segment_filename', '-movflags',
                      '-global_args', '-y'}

    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue

        if arg == "-progress" and i + 1 < len(args):
            progress_url = args[i + 1]
            skip_next = True
            continue

        if arg == "-i" and i + 1 < len(args):
            input_file = args[i + 1]
            skip_next = True
            continue

        # Check if this is a flag that takes an argument
        if arg in flag_with_args and i + 1 < len(args):
            skip_next = True
            continue

        # If it's not a flag and not part of a flag-value pair, it might be the output file
        # The output file is typically the last non-flag argument
        if not arg.startswith("-"):
            output_file = arg

    # Check for loudnorm analysis pass
    if is_loudnorm_analysis(args):
        # Simulate loudnorm analysis
        # Print some ffmpeg-like header
        print("ffmpeg version fake-ffmpeg", file=sys.stderr)
        print("  configuration: fake", file=sys.stderr)
        print("  libavutil      56. 70.100 / 56. 70.100", file=sys.stderr)

        # Simulate some progress output
        time.sleep(FAKE_DELAY * 5)

        # Print loudnorm JSON to stderr
        loudnorm_data = get_loudnorm_json()
        print("\n[Parsed_loudnorm_0 @ 0x0] ", file=sys.stderr)
        print(json.dumps(loudnorm_data, indent=2), file=sys.stderr)

        sys.exit(FAKE_EXIT_CODE)

    # Regular encoding
    # Print some ffmpeg-like output
    print("ffmpeg version fake-ffmpeg", file=sys.stderr)
    print(f"Input #0, matroska,webm, from '{input_file}':", file=sys.stderr)
    print(f"  Duration: {FAKE_DURATION:.2f}, start: 0.000000, bitrate: 8388 kb/s", file=sys.stderr)
    print(f"Output #0, mp4, to '{output_file}':", file=sys.stderr)

    # Send progress if requested
    if progress_url:
        send_progress(progress_url, FAKE_DURATION)
    else:
        # Just sleep to simulate encoding
        time.sleep(FAKE_DELAY * 10)

    # Create output file(s)
    if output_file:
        output_path = Path(output_file)

        # Handle HLS output (creates directory with segments)
        if output_path.suffix == ".m3u8":
            # Create the playlist file
            output_path.write_text("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-ENDLIST\n")

            # Create segment directory if specified in args
            for i, arg in enumerate(args):
                if arg == "-hls_segment_filename" and i + 1 < len(args):
                    segment_pattern = args[i + 1]
                    # Extract directory from pattern (e.g., "output.m3u8.ts/%04d.ts" -> "output.m3u8.ts/")
                    segment_dir = Path(segment_pattern).parent
                    segment_dir.mkdir(parents=True, exist_ok=True)
                    # Create a few fake segment files
                    for seg_num in range(3):
                        seg_file = segment_dir / f"{seg_num:04d}.ts"
                        seg_file.write_bytes(b"fake_segment_data")
                    break
        else:
            # Regular file output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake_video_data")

    sys.exit(FAKE_EXIT_CODE)


if __name__ == "__main__":
    main()
