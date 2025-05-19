#!/usr/bin/env python
import ffmpeg
import sys
import os


def main():
    args = sys.argv[1:]  # Get arguments, excluding script name

    # --- Argument Validation ---
    if len(args) < 3:  # Need at least 2 inputs and 1 output
        print(
            f"Usage: {os.path.basename(sys.argv[0])} <input1.mp4> <input2.mp4> ... <output.mp4>",
            file=sys.stderr,
        )
        print(
            "Error: Need at least two input files and one output file.", file=sys.stderr
        )
        sys.exit(1)

    output_file = args[-1]
    input_files = args[:-1]

    # --- File Existence Check ---
    for f in input_files:
        if not os.path.exists(f):
            print(f"Error: Input file not found: {f}", file=sys.stderr)
            sys.exit(1)

    print(f"Inputs: {', '.join(input_files)}")
    print(f"Output: {output_file}")

    # --- FFmpeg Processing ---
    try:
        print("Setting up and running ffmpeg...")
        inputs = [ffmpeg.input(f) for f in input_files]
        # Create a flat list of video/audio streams: [in1_v, in1_a, in2_v, in2_a, ...]
        streams_to_concat = [stream for i in inputs for stream in (i.video, i.audio)]
        concatenated = ffmpeg.concat(*streams_to_concat, v=1, a=1).node
        # Run ffmpeg: map concatenated video/audio, specify output, overwrite if exists
        ffmpeg.output(concatenated["v"], concatenated["a"], output_file).run(
            overwrite_output=True, quiet=False
        )  # quiet=False shows ffmpeg progress

        print(f"\nConcatenation successful: {output_file}")
        sys.exit(0)

    except ffmpeg.Error as e:
        print("\n--- FFmpeg Error ---", file=sys.stderr)
        try:
            print(e.stderr.decode(), file=sys.stderr)  # Show ffmpeg's error output
        except Exception:
            print(f"Error decoding ffmpeg stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected Python error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
