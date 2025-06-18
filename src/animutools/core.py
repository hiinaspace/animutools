#!/usr/bin/env python3
import ffmpeg
import sys
import os
import logging

if os.name == "posix":
    import fcntl
import json
from .progress import run_ffmpeg_with_progress
from rich.console import Console
from rich.table import Table

# Create module logger
logger = logging.getLogger("animutools")


def probe_video(infile):
    """Probe a video file and return audio/subtitle track information."""
    probe = ffmpeg.probe(infile)
    audio_track = 0
    audio_count = 0
    audio_stream = None
    sub_count = 0
    sub_track = 0
    sub_type = "text"
    found_eng_sub_track = False

    # XXX clean up spaghetti logic through here
    audio_streams = []  # Keep track of all audio streams
    for stream in probe["streams"]:
        # try to select jpn audio over english
        if stream["codec_type"] == "audio":
            audio_streams.append(stream)
            if "tags" in stream:
                tags = stream["tags"]
                if tags and "language" in tags and tags["language"] == "jpn":
                    audio_track = audio_count
            audio_count += 1
        if stream["codec_type"] == "subtitle":
            # try to select default stream
            if (
                "disposition" in stream
                and "default" in stream["disposition"]
                and stream["disposition"]["default"] == 1
            ):
                sub_track = sub_count
                if (
                    stream["codec_name"] == "dvd_subtitle"
                    or stream["codec_name"] == "hdmv_pgs_subtitle"
                ):
                    sub_type = "dvd"
            # try to select the first english sub track, which at least for these awful
            # cyberpunk rips seems to be the japanese tl track and not the dubtitles.
            # it is unfortunately completely ambiguous though.
            if (
                "tags" in stream
                and "language" in stream["tags"]
                and stream["tags"]["language"] == "eng"
            ):
                if not found_eng_sub_track:
                    sub_track = sub_count
                    found_eng_sub_track = True
                    logger.info(f"Found first English subtitle track at {sub_track}")
                    if (
                        stream["codec_name"] == "dvd_subtitle"
                        or stream["codec_name"] == "hdmv_pgs_subtitle"
                    ):
                        sub_type = "dvd"
            sub_count += 1

    # Set audio_stream to the selected track
    if audio_streams and audio_track < len(audio_streams):
        audio_stream = audio_streams[audio_track]

    return {
        "probe": probe,
        "audio_track": audio_track,
        "audio_stream": audio_stream,
        "sub_track": sub_track,
        "sub_type": sub_type,
        "audio_count": audio_count,
        "sub_count": sub_count,
    }


def analyze_audio_loudness(infile, audio_track, audio_stream, probe_result):
    """Analyze audio loudness using FFmpeg loudnorm filter first pass."""
    # Get input sample rate for resampling back later
    input_sample_rate = audio_stream.get("sample_rate", "48000")

    # Build FFmpeg command for loudnorm analysis
    analysis_stream = (
        ffmpeg.input(infile)
        .audio.filter("loudnorm", print_format="json")
        .output("pipe:", format="null")
        .global_args("-map", f"0:a:{audio_track}", "-hide_banner", "-nostats")
    )

    # Run analysis with progress tracking and stderr capture
    try:
        stderr_output = run_ffmpeg_with_progress(
            analysis_stream,
            probe_result,
            description="Analyzing audio loudness",
            capture_stderr=True,
        )

        # Extract JSON from stderr (loudnorm prints to stderr)
        json_start = stderr_output.rfind("{")
        json_end = stderr_output.rfind("}") + 1

        if json_start == -1 or json_end == 0:
            logger.error("Could not find loudnorm JSON output in FFmpeg stderr")
            sys.exit(1)

        json_str = stderr_output[json_start:json_end]
        measurements = json.loads(json_str)

        logger.info(
            f"Audio analysis complete - Input loudness: {measurements.get('input_i', 'unknown')} LUFS"
        )

        return measurements, input_sample_rate

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse loudnorm JSON output: {e}")
        sys.exit(1)


def process_video(infile, outfile, options):
    """Process a video according to the provided options."""
    # Get video information
    video_info = probe_video(infile)
    probe = video_info["probe"]
    audio_track = video_info["audio_track"]
    audio_stream = video_info["audio_stream"]
    sub_track = video_info["sub_track"]
    sub_type = video_info["sub_type"]

    if options.probe:
        logger.info("Displaying media file information")

        # Rich tables for beautiful display
        console = Console(stderr=True)

        # Video streams table
        video_table = Table(title="Video Streams")
        video_table.add_column("Stream Index", style="cyan")
        video_table.add_column("Codec", style="green")
        video_table.add_column("Resolution", style="magenta")
        video_table.add_column("Framerate", style="yellow")
        video_table.add_column("Language", style="blue")

        # Audio streams table
        audio_table = Table(title="Audio Streams")
        audio_table.add_column("Stream Index", style="cyan")
        audio_table.add_column("Codec", style="green")
        audio_table.add_column("Channels", style="magenta")
        audio_table.add_column("Sample Rate", style="yellow")
        audio_table.add_column("Language", style="blue")
        audio_table.add_column("Selected", style="red")

        # Subtitle streams table
        subtitle_table = Table(title="Subtitle Streams")
        subtitle_table.add_column("Stream Index", style="cyan")
        subtitle_table.add_column("Codec", style="green")
        subtitle_table.add_column("Language", style="blue")
        subtitle_table.add_column("Selected", style="red")

        # Fill tables with data
        for stream in probe["streams"]:
            stream_index = stream.get("index", "")
            codec = stream.get("codec_name", "")
            tags = stream.get("tags", {})
            language = tags.get("language", "und")

            if stream["codec_type"] == "video":
                width = stream.get("width", "")
                height = stream.get("height", "")
                resolution = f"{width}x{height}" if width and height else "Unknown"

                frame_rate = "Unknown"
                if "avg_frame_rate" in stream:
                    rate = stream["avg_frame_rate"].split("/")
                    if len(rate) == 2 and int(rate[1]) > 0:
                        frame_rate = f"{float(int(rate[0]) / int(rate[1])):.2f} fps"

                video_table.add_row(
                    str(stream_index), codec, resolution, frame_rate, language
                )

            elif stream["codec_type"] == "audio":
                channels = stream.get("channels", "")
                sample_rate = (
                    f"{stream.get('sample_rate', '')} Hz"
                    if "sample_rate" in stream
                    else "Unknown"
                )
                is_selected = "✓" if audio_track == stream_index else ""

                audio_table.add_row(
                    str(stream_index),
                    codec,
                    str(channels),
                    sample_rate,
                    language,
                    is_selected,
                )

            elif stream["codec_type"] == "subtitle":
                is_selected = "✓" if sub_track == stream_index else ""

                subtitle_table.add_row(str(stream_index), codec, language, is_selected)

        # Format info table
        format_table = Table(title="Format Information")
        format_table.add_column("Property", style="cyan")
        format_table.add_column("Value", style="green")

        format_info = probe.get("format", {})
        if format_info:
            duration = float(format_info.get("duration", 0))
            duration_str = f"{int(duration // 3600)}:{int((duration % 3600) // 60):02d}:{int(duration % 60):02d}"
            size_bytes = int(format_info.get("size", 0))
            size_mb = size_bytes / (1024 * 1024)

            format_table.add_row("Filename", format_info.get("filename", "Unknown"))
            format_table.add_row(
                "Format", format_info.get("format_long_name", "Unknown")
            )
            format_table.add_row("Duration", duration_str)
            format_table.add_row("Size", f"{size_mb:.2f} MB ({size_bytes:,} bytes)")
            format_table.add_row(
                "Bitrate", f"{int(format_info.get('bit_rate', 0)) // 1000} kb/s"
            )

        # Print all tables
        console.print("\n[bold]Media File Information[/bold]")
        console.print(format_table)
        console.print(video_table)
        console.print(audio_table)
        console.print(subtitle_table)

        logger.info("Media information display complete")
        sys.exit(0)

    if options.subtitle_index is not None:
        logger.info(
            f"Overriding subtitle track from {sub_track=} to {options.subtitle_index=}"
        )
        sub_track = options.subtitle_index

    logger.info(f"Selecting {audio_track=}")
    logger.info(f"Selecting {sub_track=}")

    # Set up ffmpeg inputs and filters
    ffin = ffmpeg.input(infile)
    ffv = ffin.video.filter("format", "yuv420p")
    if options.downscale_720p:
        ffv = ffv.filter("scale", "1280", "-1")
    elif options.letterbox:
        # Letterbox to fixed 16:9 aspect ratio (1.7777...)
        # First, scale to fit within 1920x1080 while preserving aspect ratio
        ffv = ffv.filter(
            "scale",
            w="min(1920,iw)",
            h="min(1080,ih)",
            force_original_aspect_ratio="decrease",
        )
        # Then pad to 16:9 aspect ratio with black bars
        ffv = ffv.filter(
            "pad",
            w="max(iw,ih*16/9)",
            h="max(ih,iw*9/16)",
            x="(ow-iw)/2",
            y="(oh-ih)/2",
            color="black",
        )

    # assume subtitle track matches the audio track
    if sub_type == "text":
        subfile = infile
        if options.subtitle_file:
            subfile = options.subtitle_file

        ffv = ffv.filter("subtitles", filename=subfile, stream_index=sub_track)
    else:
        # burn the dvd subs on the image
        subs = ffin[f"s:{sub_track}"]
        s2r = ffmpeg.filter_multi_output([subs, ffv], "scale2ref")
        ffv = s2r[1].overlay(s2r[0])

    # cap bufsize based on expected buffer duration, so there aren't
    # bitrate spikes above it and thus buffer underruns during playback.
    bufsize = int(options.target_bitrate * options.buffer_duration)

    opts = {
        "c:v": "libx264",
        # I'm not sure this is entirely necessary, but all devices support
        # high profile by now, so it doesn't seem harmful to do.
        "profile:v": "high",
        "preset": "medium",
        "tune": "animation",
        "crf": "18",
        #'b:v': '2500K',
        "maxrate": f"{options.target_bitrate}K",
        # try and cap the bitrate, it'll decrease the crf to compensate
        "bufsize": f"{bufsize}K",
        #'c:a': 'copy', TODO ideally we'd just copy existing AAC
        # but need to modify the ffprobe stuff to detect.
        "c:a": "aac",
        "b:a": "160k",
        "ac": "2",
        #'f': 'mp4',
    }

    # if remuxing, don't need the other stuff, restart
    if options.remux:
        opts = {"c": "copy"}

    if options.hls or os.path.splitext(outfile)[1] == ".m3u8":
        # encode as HLS, a bunch of .ts segment files + .m3u8 playlist,
        # which works around MediaFoundation's poor behavior (see README.md)

        # i'm not sure how necessary it is to make the keyframes nice and tidy
        # kind of annoying to have to guess the output framerate.
        # https://superuser.com/questions/908280/what-is-the-correct-way-to-fix-keyframes-in-ffmpeg-for-dash/908325#908325
        # framerate = 30
        # interval = 2
        # keyframes_per_segment = 3

        # opts['r'] = framerate
        # opts['g'] = framerate * interval
        # opts['keyint_min'] = framerate * interval
        # opts['hls_time'] = interval * keyframes_per_segment
        # https://teddit.net/r/ffmpeg/comments/nam6hg/mp4_to_hls_how_to_set_time_segments_properly/
        # not sure if necessary, according to that other superuser post
        # opts['force_key_frames:v'] = 'expr:gte(t,n_forced*2)'
        opts["f"] = "hls"
        opts["hls_playlist_type"] = "vod"
        opts["hls_time"] = options.hls_time
        opts["hls_list_size"] = 0

        # store chunks in a directory alongside the m3u8 playlist for convenience
        if not options.dry_run:
            os.makedirs(f"{outfile}.ts", exist_ok=True)
        opts["hls_base_url"] = f"{os.path.basename(outfile)}.ts/"
        opts["hls_segment_filename"] = f"{outfile}.ts/%04d.ts"
    else:
        opts["movflags"] = "faststart"

    if options.test:
        # just encode a bit to test
        opts["t"] = 60

    audio = ffin[f"a:{audio_track}"]

    if options.remux:
        output = ffmpeg.overwrite_output(ffmpeg.output(ffin, outfile, **opts))
    else:
        # Apply audio normalization
        measurements, input_sample_rate = analyze_audio_loudness(
            infile, audio_track, audio_stream, probe
        )

        audio = ffin[f"a:{audio_track}"]

        # Apply loudnorm with measurements from analysis pass
        audio = audio.filter(
            "loudnorm",
            linear=True,
            i=-14.0,  # Target -14 LUFS
            lra=7.0,
            tp=-2.0,
            measured_I=measurements["input_i"],
            measured_tp=measurements["input_tp"],
            measured_LRA=measurements["input_lra"],
            measured_thresh=measurements["input_thresh"],
        )

        # Resample back to original sample rate using soxr
        audio = audio.filter(
            "aresample", resampler="soxr", out_sample_rate=input_sample_rate
        )

        output = ffmpeg.overwrite_output(ffmpeg.output(ffv, audio, outfile, **opts))
    if options.dry_run:
        cmd_line = []
        for a in output.get_args():
            if a.startswith("-"):
                cmd_line.append(a)
            else:
                cmd_line.append(f"'{a}'")
        logger.info("FFmpeg command: " + " ".join(cmd_line))
    else:
        # basic flock queueing for multiple invocations
        if os.name == "posix":
            with open("/tmp/vrcencode", "w+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                # Use rich progress bar if progress is enabled
                if options.no_progress:
                    output.run()
                else:
                    run_ffmpeg_with_progress(
                        output, probe, "Encoding video", options.overwrite
                    )
        else:
            # no fnctl on windows
            if options.no_progress:
                output.run()
            else:
                run_ffmpeg_with_progress(
                    output, probe, "Encoding video", options.overwrite
                )

    return True
