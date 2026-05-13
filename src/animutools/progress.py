#!/usr/bin/env python3
import os
import re
import socket
import signal
import subprocess
import logging
import threading
from rich.progress import Progress, TimeElapsedColumn, SpinnerColumn

logger = logging.getLogger("animutools")


_PROGRESS_KEYS = {
    "bitrate",
    "continue",
    "drop_frames",
    "dup_frames",
    "fps",
    "frame",
    "out_time",
    "out_time_ms",
    "out_time_us",
    "progress",
    "speed",
    "total_size",
}

_FFMPEG_WARNING_RE = re.compile(
    r"error|err:|invalid|unable|fail|could not", re.IGNORECASE
)


class ProgressServer:
    """TCP server for receiving progress updates from FFmpeg."""

    def __init__(self, update_callback):
        self.update_callback = update_callback
        self.sock = None
        self.server_thread = None
        self.client_thread = None
        self.running = False
        self.url = None

    def start(self):
        """Start the progress server in a background thread."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))  # Let OS assign a port
        self.sock.listen(1)

        host, port = self.sock.getsockname()
        self.url = f"tcp://{host}:{port}"
        logger.debug(f"Progress server listening on {self.url}")

        self.running = True
        self.server_thread = threading.Thread(
            target=self._accept_connections, daemon=True
        )
        self.server_thread.start()
        return self.url

    def _accept_connections(self):
        """Accept incoming connections from FFmpeg."""
        self.sock.settimeout(1.0)  # Allow checking self.running periodically

        while self.running:
            try:
                client_sock, addr = self.sock.accept()
                logger.debug(f"Connection from {addr}")

                # Only handle one client at a time
                if self.client_thread and self.client_thread.is_alive():
                    logger.warning(
                        "Already handling a client, rejecting new connection"
                    )
                    client_sock.close()
                    continue

                self.client_thread = threading.Thread(
                    target=self._handle_client, args=(client_sock,), daemon=True
                )
                self.client_thread.start()
            except socket.timeout:
                # This is expected, just retry
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")
                break

    def _handle_client(self, client_sock):
        """Handle progress updates from an FFmpeg client."""
        buffer = b""
        client_sock.settimeout(5.0)  # Prevent hanging if FFmpeg stops sending

        try:
            # Notify that we're ready to receive updates
            self.update_callback("start", "connected")

            while self.running:
                try:
                    chunk = client_sock.recv(1024)
                    if not chunk:  # Connection closed
                        break

                    buffer += chunk

                    # Process complete lines
                    while b"\n" in buffer:
                        line_bytes, buffer = buffer.split(b"\n", 1)
                        line = line_bytes.decode(errors="ignore").strip()
                        if not line:
                            continue

                        parts = line.split("=", 1)
                        key = parts[0].strip() if len(parts) > 0 else None
                        value = parts[1].strip() if len(parts) > 1 else None

                        if key:
                            self.update_callback(key, value)
                except socket.timeout:
                    # Just retry
                    continue
                except Exception as e:
                    logger.debug(f"Error reading from client: {e}")
                    break
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def stop(self):
        """Stop the progress server."""
        self.running = False

        # Close the server socket
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.debug(f"Error closing server socket: {e}")

        # Wait for threads to terminate
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)

        if self.client_thread and self.client_thread.is_alive():
            self.client_thread.join(timeout=1.0)

        logger.debug("Progress server stopped")


def probe_duration(probe_result):
    """Extract duration from FFmpeg probe result."""
    duration = 0
    try:
        if "format" in probe_result and "duration" in probe_result["format"]:
            duration = float(probe_result["format"]["duration"])
    except (ValueError, TypeError):
        logger.warning("Could not parse video duration")
    return duration


def _is_progress_key(key):
    return key in _PROGRESS_KEYS or (
        key.startswith("stream_") and key.endswith("_q")
    )


def _split_progress_line(line):
    if "=" not in line:
        return None, None

    key, value = line.split("=", 1)
    key = key.strip()
    if not _is_progress_key(key):
        return None, None

    return key, value.strip()


def _parse_progress_seconds(key, value):
    try:
        if key in {"out_time_ms", "out_time_us"}:
            return float(value) / 1_000_000.0

        if key == "out_time":
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError, OverflowError):
        return None

    return None


def _compile_ffmpeg_command(ffmpeg_stream, overwrite=False, progress=False):
    """Compile an ffmpeg-python stream with global args before the inputs.

    ffmpeg-python's global_args()/overwrite_output() append options after the
    output URL, which can produce "Trailing option(s)" warnings for options like
    -map and can make progress handling unreliable. Keep known global flags in
    one valid place instead.
    """
    cmd = ffmpeg_stream.compile()
    if not cmd:
        raise RuntimeError("Could not compile FFmpeg command")

    executable = os.environ.get("FFMPEG_BINARY", cmd[0])
    args = cmd[1:]
    filtered_args = []
    saw_overwrite = False
    index = 0

    while index < len(args):
        arg = args[index]

        if arg == "-progress":
            index += 2
            continue

        if arg in {"-hide_banner", "-nostats"}:
            index += 1
            continue

        if arg == "-y":
            saw_overwrite = True
            index += 1
            continue

        filtered_args.append(arg)
        index += 1

    global_args = []
    if overwrite or saw_overwrite:
        global_args.append("-y")

    global_args.extend(["-hide_banner", "-nostats"])
    if progress:
        global_args.extend(["-progress", "pipe:2"])

    return [executable, *global_args, *filtered_args]


def _process_group_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

    return {"start_new_session": True}


def _terminate_process(process):
    if process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
    except Exception:
        try:
            process.terminate()
        except Exception:
            pass

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("FFmpeg process did not exit after forced termination")


def _log_ffmpeg_line(line):
    if not line:
        return

    if _FFMPEG_WARNING_RE.search(line):
        logger.warning(f"FFmpeg: {line}")
    else:
        logger.debug(f"FFmpeg: {line}")


def _run_ffmpeg_process(cmd, capture_stderr=False, progress_callback=None):
    stderr_buffer = []
    process = None

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
            **_process_group_kwargs(),
        )

        if process.stderr is not None:
            for raw_line in process.stderr:
                line = raw_line.rstrip("\r\n")
                if capture_stderr:
                    stderr_buffer.append(line)

                key, value = _split_progress_line(line)
                if key:
                    if progress_callback:
                        progress_callback(key, value)
                    continue

                _log_ffmpeg_line(line)

        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError(f"FFmpeg exited with code {returncode}")

    except KeyboardInterrupt:
        if process is not None:
            _terminate_process(process)
        raise
    except Exception:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        raise

    if capture_stderr:
        return "\n".join(stderr_buffer)

    return None


def run_ffmpeg_with_progress(
    ffmpeg_stream,
    probe_result,
    description="Encoding",
    overwrite=False,
    capture_stderr=False,
):
    """Run FFmpeg with a Rich progress bar.

    Args:
        ffmpeg_stream: The ffmpeg-python stream to run
        probe_result: The probe result from ffmpeg.probe()
        description: Text to show in the progress bar
        overwrite: Whether to force overwriting output files
    """
    duration = probe_duration(probe_result)

    show_progress = duration > 0
    if not show_progress:
        logger.warning("Cannot show progress - unknown duration")

    cmd = _compile_ffmpeg_command(
        ffmpeg_stream, overwrite=overwrite, progress=show_progress
    )

    previous_level = logger.level
    if logger.level <= logging.INFO:
        # Set to INFO instead of WARNING to show important messages
        logger.setLevel(logging.INFO)

    if show_progress:
        logger.info(f"Starting encoding process ({duration:.2f} seconds)")
    else:
        logger.info("Starting FFmpeg process")

    try:
        if not show_progress:
            return _run_ffmpeg_process(cmd, capture_stderr=capture_stderr)

        with Progress(
            SpinnerColumn(),
            *Progress.get_default_columns(),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task(description, total=duration)

            def update_progress(key, value):
                time_sec = _parse_progress_seconds(key, value)
                if time_sec is not None:
                    progress.update(task, completed=min(time_sec, duration))
                elif key == "progress" and value == "end":
                    progress.update(task, completed=duration)

            stderr_output = _run_ffmpeg_process(
                cmd,
                capture_stderr=capture_stderr,
                progress_callback=update_progress,
            )

            progress.update(task, completed=duration)
            logger.info("Encoding completed successfully")
            return stderr_output

    except KeyboardInterrupt:
        logger.warning("Encoding interrupted by user")
        raise
    finally:
        logger.setLevel(previous_level)
