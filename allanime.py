#!/usr/bin/env python3
import ffmpeg
import sys
import os
import tempfile
import shutil
import asyncio  # Use asyncio
from contextlib import asynccontextmanager  # Use async context manager
from more_itertools import chunked
from tqdm import tqdm

# No more gevent monkey patching

# --- Helper functions for asyncio progress bar ---


async def _handle_ffmpeg_progress(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, handler
):
    """Coroutine to read progress data from FFmpeg connection and call handler."""
    peername = writer.get_extra_info("peername")
    print(f"Progress reporting connection established from {peername}", file=sys.stderr)
    data = b""
    try:
        while not reader.at_eof():
            # Read chunks of data, attempting to read until newline
            # Use read() instead of readuntil() for more robustness against partial writes/reads
            chunk = await reader.read(1024)
            if not chunk:
                # Should be caught by reader.at_eof() but good practice
                break
            data += chunk
            # Process complete lines
            while b"\n" in data:
                line_bytes, data = data.split(b"\n", 1)
                line = line_bytes.decode(errors="ignore").strip()
                if not line:
                    continue
                parts = line.split("=", 1)
                key = parts[0].strip() if len(parts) > 0 else None
                value = parts[1].strip() if len(parts) > 1 else None
                if key:
                    handler(key, value)

        # Process any remaining data after EOF
        if data:
            line = data.decode(errors="ignore").strip()
            if line:
                parts = line.split("=", 1)
                key = parts[0].strip() if len(parts) > 0 else None
                value = parts[1].strip() if len(parts) > 1 else None
                if key:
                    handler(key, value)

    except asyncio.CancelledError:
        print("Progress handler task cancelled.", file=sys.stderr)
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(
            f"Progress connection closed unexpectedly ({type(e).__name__}).",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"Error in progress handler coroutine: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        # import traceback # Uncomment for detailed debug
        # traceback.print_exc()
    finally:
        print(f"Closing progress connection from {peername}", file=sys.stderr)
        writer.close()
        try:
            # Ensure the writer is fully closed
            await writer.wait_closed()
        except Exception:
            pass  # Ignore errors during final close


@asynccontextmanager
async def _watch_progress(handler):
    """Async context manager for creating/listening on a TCP socket for FFmpeg progress."""
    server = None
    listen_task = None
    host = "127.0.0.1"
    port = 0  # Let OS choose port
    progress_url = None

    # Define the callback for new connections
    async def connection_callback(reader, writer):
        # We only expect one connection from FFmpeg per server instance
        nonlocal listen_task
        if listen_task and not listen_task.done():
            print(
                "Warning: Received unexpected second connection for progress. Ignoring.",
                file=sys.stderr,
            )
            writer.close()
            await writer.wait_closed()
            return
        # Create task to handle this specific connection
        listen_task = asyncio.create_task(
            _handle_ffmpeg_progress(reader, writer, handler)
        )

    try:
        # Start the server
        server = await asyncio.start_server(connection_callback, host, port)
        async with server:  # Ensure server is properly closed
            addr = server.sockets[0].getsockname()
            progress_url = f"tcp://{addr[0]}:{addr[1]}"
            print(f"Progress listener waiting on {progress_url}", file=sys.stderr)

            # Yield the URL for FFmpeg's -progress argument
            yield progress_url

            # Wait for the server to naturally stop serving or ffmpeg to disconnect
            # The listen_task handles the actual communication.
            # We need to keep the server running while ffmpeg might connect.
            # The outer context (show_progress + ffmpeg execution) controls duration.
            print(
                "Progress server yielding control, ffmpeg should connect soon...",
                file=sys.stderr,
            )

    except Exception as e:
        print(f"Error setting up/running TCP progress server: {e}", file=sys.stderr)
        raise  # Re-raise the exception
    finally:
        print("Exiting progress server context.", file=sys.stderr)
        # Server is closed by 'async with server:'
        # Cancel the connection handler task if it's still running
        if listen_task and not listen_task.done():
            print("Cancelling active progress handler task.", file=sys.stderr)
            listen_task.cancel()
            try:
                await listen_task  # Wait for cancellation to complete
            except asyncio.CancelledError:
                pass  # Expected
            except Exception as e:
                print(f"Error awaiting cancelled listen_task: {e}", file=sys.stderr)


@asynccontextmanager
async def show_progress(total_duration, desc="Progress"):
    """Async context manager that sets up progress watching and displays a tqdm bar."""
    if total_duration <= 0:
        print(
            f"Warning: Cannot show progress bar [{desc}] with non-positive total duration ({total_duration:.2f}s).",
            file=sys.stderr,
        )
        yield None
        return

    bar = None
    progress_url = None
    try:
        rounded_total = round(total_duration, 2)
        bar = tqdm(total=rounded_total, unit="s", desc=desc, leave=True)

        def handler(key, value):
            if bar is None:
                return
            if key == "out_time_ms":
                try:
                    time_sec = float(value) / 1_000_000.0
                    increment = time_sec - bar.n
                    # Cap increment to avoid overshooting due to timing issues or large jumps
                    capped_increment = min(max(0, increment), bar.total - bar.n)
                    if capped_increment > 0:
                        # Round update value for smoother display
                        bar.update(round(capped_increment, 2))
                except (ValueError, TypeError, OverflowError):
                    pass
            elif key == "progress" and value == "end":
                if bar.n < bar.total:
                    bar.update(bar.total - bar.n)

        # Use the async _watch_progress context manager
        async with _watch_progress(handler) as url:
            progress_url = url
            yield progress_url  # Yield the tcp://... URL

    except Exception as e:
        print(f"Error during progress display setup [{desc}]: {e}", file=sys.stderr)
        if bar:
            bar.close()
        yield None  # Indicate failure/disabled
    finally:
        if bar:
            bar.close()
        print(f"Progress context [{desc}] finished.", file=sys.stderr)


# --- Main Encoding Logic (Now Async) ---


def singleencode(f, horiz, vert):
    # This function remains synchronous as it just builds the ffmpeg-python graph
    ff = ffmpeg.input(f).video
    ff = ff.filter("fps", fps="ntsc_film")
    if f.lower().endswith(".mkv"):
        try:
            probe = ffmpeg.probe(f, select_streams="s")
            if probe.get("streams"):
                ff = ff.filter("subtitles", filename=f)
        except ffmpeg.Error as e:
            print(
                f"Warning: Could not probe subtitles for {f}: {e.stderr.decode(errors='ignore')}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"Warning: Error probing subtitles for {f}: {e}", file=sys.stderr)

    return (
        ff.filter("scale", int(horiz), int(vert))
        .filter("setsar", "1")
        .filter("format", "yuv420p")
    )


def probe_duration(filename):
    """Probes a single file for its duration. Returns float or 0.0 on error."""
    try:
        print(f"  Probing duration for: {os.path.basename(filename)}", file=sys.stderr)
        probe = ffmpeg.probe(filename)
        duration_str = probe.get("format", {}).get("duration")
        if duration_str:
            try:
                return float(duration_str)
            except ValueError:
                pass  # Fall through if format duration is invalid
        # Fallback: Check video streams if format duration missing/invalid
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                duration_str = stream.get("duration")
                if duration_str:
                    try:
                        return float(duration_str)
                    except ValueError:
                        pass  # Ignore invalid stream duration
                break  # Use first video stream found
        print(
            f"  Warning: Could not find valid duration in format or video stream for {os.path.basename(filename)}",
            file=sys.stderr,
        )
        return 0.0
    except ffmpeg.Error as e:
        print(
            f"  Warning: ffmpeg probe failed for {filename}: {e.stderr.decode(errors='ignore')}",
            file=sys.stderr,
        )
        return 0.0
    except Exception as e:
        print(f"  Warning: Error probing {filename}: {e}", file=sys.stderr)
        return 0.0


def get_max_duration(input_files):
    """Probes input files to find the maximum duration."""
    max_duration = 0.0
    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff")
    print("Probing input files for maximum duration...", file=sys.stderr)
    for f in input_files:
        if f.lower().endswith(image_extensions):
            continue
        duration = probe_duration(f)
        if duration > max_duration:
            max_duration = duration

    if max_duration <= 0.0:
        print(
            "Warning: Could not determine maximum duration. Progress bar for Step 1 might be inaccurate or disabled.",
            file=sys.stderr,
        )
        return 0.0

    print(
        f"Determined maximum duration for Step 1: {max_duration:.2f}s", file=sys.stderr
    )
    return max_duration


# Use run_in_executor to run the blocking ffmpeg command
def run_ffmpeg_blocking(stream):
    """Wrapper to run ffmpeg-python's blocking run method."""
    # We capture output here to potentially analyze/log it,
    # but main output/error goes to parent process stderr/stdout by default.
    # Use capture_stdout/stderr=True if you want to suppress it from console.
    return stream.run(capture_stdout=False, capture_stderr=False)


async def encode(input_files, output_file):
    # Make the main encode function async
    temp_dir = None
    duration_step1 = get_max_duration(input_files)
    loop = asyncio.get_running_loop()  # Get the current event loop

    try:
        # --- Step 1: Create the grid video and output to a temporary file ---
        temp_dir = tempfile.mkdtemp(prefix="ffmpeg_grid_")
        temp_filename = os.path.join(temp_dir, "intermediate.mp4")
        print(f"\nIntermediate file will be: {temp_filename}", file=sys.stderr)

        columns = 3
        horiz = 1920 / columns
        vert = horiz * 9 / 16

        video_inputs = [singleencode(f, horiz, vert) for f in input_files]
        hstacks = [
            ffmpeg.filter(chunk, "hstack", inputs=min(columns, len(chunk)))
            for chunk in chunked(video_inputs, columns)
        ]
        vstack = ffmpeg.filter(hstacks, "vstack", inputs=len(hstacks))

        audio_inputs_raw = [
            ffmpeg.input(f).audio
            for f in input_files
            if not f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))
        ]
        num_audio_streams = len(audio_inputs_raw)

        if not audio_inputs_raw:
            print("Warning: No audio inputs found.", file=sys.stderr)
            audio_outputs = []
        else:
            audio_outputs = [a.filter("loudnorm") for a in audio_inputs_raw]
            print(f"Prepared {num_audio_streams} audio streams.", file=sys.stderr)

        video_opts = {
            "c:v": "libx264",
            "preset": "medium",
            "tune": "animation",
            "b:v": "2000k",
            "maxrate": "2000k",
            "bufsize": "4000k",
            "g": "50",
            "crf": "28",
        }
        audio_opts_step1 = {"c:a": "aac", "b:a": "160k", "ac": "1"}
        opts1 = {**video_opts, **audio_opts_step1}

        global_args1 = [
            "-map_chapters",
            "-1",
            "-sn",
            "-nostdin",
            "-nostats",
        ]  # Base args

        # Use the async show_progress context manager for Step 1
        async with show_progress(
            duration_step1, desc="Step 1: Encoding Grid"
        ) as progress_url1:
            current_global_args = list(global_args1)  # Copy base args
            if progress_url1:
                print(
                    f"Using progress URL for Step 1: {progress_url1}", file=sys.stderr
                )
                current_global_args.extend(["-progress", progress_url1])
            else:
                print("Proceeding Step 1 without progress reporting.", file=sys.stderr)

            stream1_args = [vstack] + audio_outputs
            stream1 = ffmpeg.output(*stream1_args, temp_filename, **opts1).global_args(
                *current_global_args
            )

            print("\n--- Step 1: Encoding to intermediate file ---", file=sys.stderr)
            print(f"Command: {' '.join(stream1.get_args())}", file=sys.stderr)
            try:
                # Run blocking ffmpeg call in executor, await its completion
                await loop.run_in_executor(None, run_ffmpeg_blocking, stream1)
                print("--- Step 1: FFmpeg process finished. ---", file=sys.stderr)
            except ffmpeg.Error as e:
                # Error is propagated from the executor
                print("\n--- FFmpeg Error (Step 1) ---", file=sys.stderr)
                # stderr from ffmpeg usually goes to console directly, but if captured:
                if e.stderr:
                    print(e.stderr.decode(errors="ignore"), file=sys.stderr)
                print("----------------------------", file=sys.stderr)
                raise  # Re-raise to stop execution

        print("--- Step 1: Intermediate file created. ---", file=sys.stderr)

        # --- Step 2: Re-encode video, copy audio from temporary file ---
        print(
            "\n--- Step 2: Re-encoding video / Copying audio to final file ---",
            file=sys.stderr,
        )

        # Probe intermediate file for duration for Step 2 progress bar
        duration_step2 = probe_duration(temp_filename)

        in_temp = ffmpeg.input(temp_filename)
        mapped_streams = [in_temp["v:0"]]
        for i in range(num_audio_streams):
            mapped_streams.append(in_temp[f"a:{i}"])

        if not mapped_streams:
            raise ValueError(
                "No streams found in intermediate file. Step 1 likely failed."
            )

        opts2 = {
            **video_opts,  # Reuse video opts
            "c:a": "copy",
            "map_metadata": "-1",
            "map_chapters": "-1",
            "movflags": "+faststart",
        }

        global_args2 = ["-nostdin", "-nostats"]  # Base args for step 2

        # Use the async show_progress context manager for Step 2
        async with show_progress(
            duration_step2, desc="Step 2: Final Encode"
        ) as progress_url2:
            current_global_args = list(global_args2)
            if progress_url2:
                print(
                    f"Using progress URL for Step 2: {progress_url2}", file=sys.stderr
                )
                current_global_args.extend(["-progress", progress_url2])
            else:
                print("Proceeding Step 2 without progress reporting.", file=sys.stderr)

            stream2 = ffmpeg.output(*mapped_streams, output_file, **opts2).global_args(
                *current_global_args
            )

            print(f"Command: {' '.join(stream2.get_args())}", file=sys.stderr)
            try:
                # Run blocking ffmpeg call in executor
                await loop.run_in_executor(None, run_ffmpeg_blocking, stream2)
                print("--- Step 2: FFmpeg process finished. ---", file=sys.stderr)
            except ffmpeg.Error as e:
                print("\n--- FFmpeg Error (Step 2) ---", file=sys.stderr)
                if e.stderr:
                    print(e.stderr.decode(errors="ignore"), file=sys.stderr)
                print("----------------------------", file=sys.stderr)
                raise

        print(f"--- Step 2: Final file '{output_file}' created ---", file=sys.stderr)

    # Keep general exception handling outside async parts if possible,
    # although errors from await calls will be caught here too.
    except ffmpeg.Error:
        # Catch errors raised from within the async block
        print("\nAn ffmpeg error occurred during execution.", file=sys.stderr)
        # Error details should have been printed already
        sys.exit(1)
    except Exception as e:
        print(
            f"\nAn unexpected Python error occurred: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # --- Cleanup ---
        if temp_dir and os.path.exists(temp_dir):
            try:
                # Use shutil.rmtree which is blocking, acceptable in finally
                shutil.rmtree(temp_dir)
                print(
                    f"Cleaned up intermediate files directory: {temp_dir}",
                    file=sys.stderr,
                )
            except OSError as e:
                print(
                    f"Error removing intermediate files directory {temp_dir}: {e}",
                    file=sys.stderr,
                )


# --- Script Execution ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input1> [input2...] <output_file>")
        sys.exit(1)

    input_files = sys.argv[1:-1]
    output_file = sys.argv[-1]

    # Run the main async function using asyncio.run()
    try:
        asyncio.run(encode(input_files, output_file))
        print("\nScript finished successfully.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Catch any exceptions that might escape asyncio.run (less common)
        print(f"An top-level error occurred: {e}", file=sys.stderr)
        sys.exit(1)
