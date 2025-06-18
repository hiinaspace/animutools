#!/usr/bin/env python3
import argparse
import sys
import logging
from rich.logging import RichHandler
from .core import process_video


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Encode video files with specific settings for anime content. When --bulk is used, infile is treated as a video directory and outfile as an output pattern supporting {num} for episode number."
    )
    parser.add_argument(
        "infile", help="input video file (or directory if --bulk is used)"
    )
    parser.add_argument(
        "outfile",
        help="output video file (or output pattern if --bulk is used, e.g., 'processed_ep{num}.mkv'). Must contain {num} if --bulk is used.",
    )
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="process multiple files from a directory. Infile becomes video_directory and outfile becomes output_pattern that must contain {num} for the zero-padded episode number (e.g. 'ep{num}.mkv').",
    )
    parser.add_argument(
        "--subtitle_index", type=int, help="specific subtitle track index to use"
    )
    parser.add_argument(
        "--subtitle_file",
        help="external subtitle file to use instead of embedded subtitles",
    )
    parser.add_argument(
        "--downscale_720p",
        action="store_true",
        help="downscale video to 720p (1280x720)",
    )
    parser.add_argument(
        "--letterbox",
        action="store_true",
        help="letterbox the video to a fixed 16:9 aspect ratio with max 1920x1080 resolution",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="encode only the first 60 seconds for testing",
    )
    parser.add_argument(
        "--target_bitrate",
        type=int,
        default=10000,
        help="target bitrate in kb/s. Default: 10000",
    )
    parser.add_argument(
        "--buffer_duration",
        type=float,
        default=1,
        help="target buffer duration in seconds. Default: 1",
    )
    parser.add_argument(
        "--hls",
        action="store_true",
        help="output HLS playlist, with ts chunks in an {outfile}.ts directory",
    )
    parser.add_argument(
        "--hls_time",
        default=4,
        type=float,
        help="hls segment time in seconds. Default: 4",
    )
    parser.add_argument(
        "--dry_run", action="store_true", help="just output ffmpeg invocation and exit"
    )
    parser.add_argument(
        "--remux",
        action="store_true",
        help="instead of transcoding, just remux (to hls)",
    )
    parser.add_argument(
        "--probe", action="store_true", help="print media file information and exit"
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable progress bar and show raw ffmpeg output",
    )
    parser.add_argument(
        "--overwrite",
        "-y",
        action="store_true",
        help="overwrite output files without asking",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="enable verbose logging output"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress all non-error messages"
    )

    return parser.parse_args()


def main():
    """Main entry point for the CLI."""
    try:
        args = parse_args()

        # Set up simple Rich logging to stderr
        level = logging.INFO
        if args.verbose:
            level = logging.DEBUG
        elif args.quiet:
            level = logging.ERROR

        logging.basicConfig(
            level=level,
            handlers=[
                RichHandler(
                    level=level,
                )
            ],
        )

        # Create logger for this module
        logging.getLogger("animutools")

        process_video(args.infile, args.outfile, args)
    except KeyboardInterrupt:
        logging.error("Encoding interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
