#!/usr/bin/env python3
import socket
import logging
import threading
from rich.progress import Progress, TimeElapsedColumn, SpinnerColumn
from rich.console import Console

# Create logger but don't configure it - CLI will handle configuration
logger = logging.getLogger("animutools")
console = Console()

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
        self.sock.bind(('127.0.0.1', 0))  # Let OS assign a port
        self.sock.listen(1)

        host, port = self.sock.getsockname()
        self.url = f'tcp://{host}:{port}'
        logger.debug(f"Progress server listening on {self.url}")

        self.running = True
        self.server_thread = threading.Thread(
            target=self._accept_connections,
            daemon=True
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
                    logger.warning("Already handling a client, rejecting new connection")
                    client_sock.close()
                    continue

                self.client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True
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
        buffer = b''
        client_sock.settimeout(5.0)  # Prevent hanging if FFmpeg stops sending

        try:
            # Notify that we're ready to receive updates
            self.update_callback('start', 'connected')

            while self.running:
                try:
                    chunk = client_sock.recv(1024)
                    if not chunk:  # Connection closed
                        break

                    buffer += chunk

                    # Process complete lines
                    while b'\n' in buffer:
                        line_bytes, buffer = buffer.split(b'\n', 1)
                        line = line_bytes.decode(errors='ignore').strip()
                        if not line:
                            continue

                        parts = line.split('=', 1)
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
        if 'format' in probe_result and 'duration' in probe_result['format']:
            duration = float(probe_result['format']['duration'])
    except (ValueError, TypeError):
        logger.warning("Could not parse video duration")
    return duration

def run_ffmpeg_with_progress(ffmpeg_stream, probe_result, description="Encoding", overwrite=False):
    """Run FFmpeg with a Rich progress bar.

    Args:
        ffmpeg_stream: The ffmpeg-python stream to run
        probe_result: The probe result from ffmpeg.probe()
        description: Text to show in the progress bar
        overwrite: Whether to force overwriting output files
    """
    duration = probe_duration(probe_result)

    if duration <= 0:
        # No progress if duration unknown
        logger.warning("Cannot show progress - unknown duration")
        ffmpeg_stream.run(capture_stdout=False, capture_stderr=False)
        return

    # Keep track of whether ffmpeg completed successfully
    ffmpeg_success = False
    server = None

    # Add overwrite option if requested
    if overwrite:
        ffmpeg_stream = ffmpeg_stream.global_args('-y')

    # Store the previous log level and temporarily reduce logging during encoding
    previous_level = logger.level
    if logger.level <= logging.INFO:
        # Set to INFO instead of WARNING to show important messages
        logger.setLevel(logging.INFO)

    try:
        with Progress(
                    SpinnerColumn(),
                    *Progress.get_default_columns(),
                    TimeElapsedColumn(),
                ) as progress:
            # Create the task but don't start it until FFmpeg connects
            task = progress.add_task(description, total=duration, start=False)

            # Create a flag to track whether FFmpeg has connected
            connected = False

            # Define the progress update callback
            def update_progress(key, value):
                nonlocal connected

                if key == 'start' and value == 'connected':
                    # Start the progress bar when connection is established
                    connected = True
                    progress.start_task(task)
                elif key == 'out_time_ms':
                    try:
                        time_sec = float(value) / 1_000_000.0
                        # Set absolute position to avoid drift
                        progress.update(task, completed=min(time_sec, duration))
                    except (ValueError, TypeError, OverflowError):
                        pass
                elif key == 'progress' and value == 'end':
                    # Ensure we show 100% completion
                    progress.update(task, completed=duration)

            # Start the progress server
            server = ProgressServer(update_progress)
            progress_url = server.start()

            logger.info(f"Starting encoding process ({duration:.2f} seconds)")

            # Add progress URL to ffmpeg stream and disable FFmpeg's own stats output
            # Also add -hide_banner to reduce noise
            stream_with_progress = ffmpeg_stream.global_args('-progress', progress_url, '-nostats', '-hide_banner')

            # Run FFmpeg in a subprocess, capturing output
            try:
                import subprocess
                import io
                import queue
                import re

                # Get command as list of strings
                cmd = stream_with_progress.compile()

                # Start FFmpeg process with pipe for stderr
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                # Queue for output lines
                output_queue = queue.Queue()
                stop_monitoring = threading.Event()

                # Monitor FFmpeg output in a separate thread
                def monitor_output():
                    try:
                        for line in process.stderr:
                            line = line.strip()
                            if line and not stop_monitoring.is_set():
                                output_queue.put(line)
                    except (ValueError, IOError):
                        # Pipe may be closed
                        pass
                    except Exception as e:
                        logger.debug(f"Error reading FFmpeg output: {e}")

                # Start output monitoring thread
                output_thread = threading.Thread(
                    target=monitor_output,
                    daemon=True
                )
                output_thread.start()

                # Thread to process and filter output
                def process_output():
                    try:
                        while not stop_monitoring.is_set():
                            try:
                                line = output_queue.get(timeout=0.5)

                                # Skip progress lines (we handle them via TCP)
                                if line.startswith('frame=') or line.startswith('size='):
                                    continue

                                # Warnings and errors get higher log levels
                                if re.search(r'error|err:|invalid|unable|fail|could not', line, re.IGNORECASE):
                                    logger.warning(f"FFmpeg: {line}")
                                else:
                                    logger.debug(f"FFmpeg: {line}")

                                output_queue.task_done()
                            except queue.Empty:
                                continue
                    except Exception as e:
                        logger.debug(f"Error processing FFmpeg output: {e}")

                # Start processing thread
                process_thread = threading.Thread(
                    target=process_output,
                    daemon=True
                )
                process_thread.start()

                # Wait for completion
                process.wait()

                # Stop the output monitoring
                stop_monitoring.set()

                # Wait for output threads to finish processing
                if output_thread.is_alive():
                    output_thread.join(timeout=1.0)
                if process_thread.is_alive():
                    process_thread.join(timeout=1.0)

                # Check if FFmpeg succeeded
                if process.returncode == 0:
                    ffmpeg_success = True

                    # If FFmpeg completed but never connected, that's strange
                    if not connected:
                        logger.warning("FFmpeg completed without sending progress updates")

                    # Ensure progress bar reaches 100%
                    progress.update(task, completed=duration)

                    logger.info("Encoding completed successfully")
                else:
                    logger.error(f"FFmpeg failed with exit code {process.returncode}")
                    raise RuntimeError(f"FFmpeg exited with code {process.returncode}")

            except Exception as e:
                logger.error(f"FFmpeg encoding failed: {e}")
                raise

    except KeyboardInterrupt:
        logger.warning("Encoding interrupted by user")
        raise
    except Exception as e:
        logger.error(f"Error during progress monitoring: {e}")
        if not ffmpeg_success:
            # Try again without progress if we failed during setup
            logger.warning("Attempting to run without progress monitoring")
            ffmpeg_stream.run(capture_stdout=False, capture_stderr=False)
    finally:
        # Stop the progress server
        if server:
            server.stop()

        # Restore previous log level
        logger.setLevel(previous_level)
