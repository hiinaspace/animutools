#!/usr/bin/env python3
import argparse
import sys
import logging
import os
from guessit import guessit
from rich.table import Table
from rich.prompt import Confirm
from rich.logging import RichHandler
from .core import process_video
from .console import console

logger = logging.getLogger("animutools")


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
        "--scale",
        type=str,
        help="downscale/upscale video using ffmpeg scale filter (e.g., '1280:720', '640:-1'). Replaces --downscale_720p.",
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
    args = parse_args()

    # Set up simple Rich logging to stderr
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.ERROR

    logging.basicConfig(
        level=level,
        format="%(message)s",  # RichHandler will format it, this avoids double logger name
        handlers=[
            RichHandler(
                level=level,
                rich_tracebacks=True,
                show_path=False,  # Shorter path in logs
            )
        ],
    )

    try:
        if args.bulk:
            do_bulk_processing(args)
        else:
            # This is the existing logic for single file processing
            # Ensure output directory exists for single file processing too
            output_dir = os.path.dirname(args.outfile)
            if output_dir and not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    logger.info(
                        f"Created output directory for single file: {output_dir}"
                    )
                except OSError as e:
                    logger.error(
                        f"Could not create output directory {output_dir} for single file: {e}"
                    )
                    sys.exit(1)
            process_video(args.infile, args.outfile, args)

    except KeyboardInterrupt:
        logger.error("Encoding interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(
            f"An unexpected error occurred: {e}", exc_info=args.verbose
        )  # Show traceback if verbose
        sys.exit(1)


def do_bulk_processing(args):
    video_directory = args.infile
    output_pattern = args.outfile

    if not os.path.isdir(video_directory):
        logger.error(f"Error: Input directory '{video_directory}' not found.")
        sys.exit(1)

    if "{num}" not in output_pattern:
        logger.error(
            "Error: Output pattern must contain '{num}' for the episode number."
        )
        sys.exit(1)

    files_to_process = []
    valid_extensions = (".mkv", ".mp4")

    logger.info(
        f"Scanning directory: {video_directory} for files ending with {valid_extensions}"
    )
    filenames = os.listdir(video_directory)
    filenames.sort()  # Sort in ascending order
    for filename in filenames:
        if filename.lower().endswith(valid_extensions):
            input_filepath = os.path.join(video_directory, filename)
            logger.debug(f"Found matching file: {filename}")
            info = guessit(filename)
            episode_number = info.get("episode")

            if isinstance(episode_number, int):
                ep_num_str = str(episode_number).zfill(2)
                try:
                    output_filename_part = output_pattern.format(num=ep_num_str)
                except (
                    KeyError
                ):  # Catching if {num} is not the only placeholder or mistyped
                    logger.error(
                        f"Error: Invalid placeholder in output pattern '{output_pattern}'. Ensure it only uses '{{num}}'."
                    )
                    sys.exit(1)

                # Output files are in the same directory as input_filepath's directory
                output_filepath = os.path.join(
                    os.path.dirname(input_filepath), output_filename_part
                )

                # Ensure output directory exists if pattern includes a path structure
                # This check is more robust if output_filepath could be outside video_directory
                output_dir_for_file = os.path.dirname(output_filepath)
                if output_dir_for_file and not os.path.exists(output_dir_for_file):
                    try:
                        os.makedirs(output_dir_for_file, exist_ok=True)
                        logger.info(f"Created output directory: {output_dir_for_file}")
                    except OSError as e:
                        logger.error(
                            f"Could not create output directory {output_dir_for_file} for {output_filename_part}: {e}. Skipping."
                        )
                        continue

                output_exists = os.path.exists(output_filepath)
                files_to_process.append(
                    {
                        "input": input_filepath,
                        "output": output_filepath,
                        "original_input_filename": filename,
                        "exists": output_exists,
                    }
                )
                logger.debug(
                    f"Added to processing list: {filename} -> {output_filepath}, Exists: {output_exists}"
                )
            else:
                logger.warning(
                    f"Could not determine episode number for '{filename}'. Skipping."
                )

    if not files_to_process:
        logger.info(
            "No video files found matching criteria or no episode numbers could be determined. Exiting."
        )
        sys.exit(0)

    table = Table(title="Bulk Processing Plan - Files to Encode")
    table.add_column("Input Filename", style="cyan")
    table.add_column(
        "Guessed Output Filename",
        style="magenta",
    )
    table.add_column("Output Exists?", style="green")

    for file_info in files_to_process:
        table.add_row(
            file_info["original_input_filename"],
            os.path.basename(file_info["output"]),
            "✅" if file_info["exists"] else "❌",
        )

    console.print(table)

    proceed_with_encoding = args.overwrite
    if not args.overwrite:
        proceed_with_encoding = Confirm.ask(
            "Proceed with encoding files marked with ❌ (non-existing)?",
            default=False,
        )

    if not proceed_with_encoding:
        logger.info("User cancelled operation. Exiting.")
        sys.exit(0)

    logger.info("Starting batch encoding process...")
    successful_encodes = 0
    skipped_encodes = 0
    failed_encodes = 0

    for file_info in files_to_process:
        input_f = file_info["input"]
        output_f = file_info["output"]

        # Check again if output exists, in case it was created since the table was shown,
        # or if user wants to skip existing files without global --overwrite
        if not args.overwrite and os.path.exists(output_f):
            logger.info(f"Skipping (already exists): {os.path.basename(output_f)}")
            skipped_encodes += 1
            continue

        logger.info(
            f"Processing: '{file_info['original_input_filename']}' -> '{os.path.basename(output_f)}'"
        )
        try:
            # Assuming process_video takes (infile, outfile, args_object)
            # We pass the original 'args' object, which carries all other encoding options
            process_video(input_f, output_f, args)
            successful_encodes += 1
            logger.info(f"Successfully processed: {os.path.basename(output_f)}")
        except Exception as e:
            failed_encodes += 1
            logger.error(
                f"Failed to process {file_info['original_input_filename']}: {e}",
                exc_info=args.verbose,
            )

    logger.info("--------------------")
    logger.info("Bulk Processing Summary:")
    logger.info(f"  Successful: {successful_encodes}")
    logger.info(f"  Skipped (already existed): {skipped_encodes}")
    logger.info(f"  Failed: {failed_encodes}")
    logger.info("--------------------")


if __name__ == "__main__":
    main()
