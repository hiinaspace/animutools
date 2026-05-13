"""Tests for progress tracking functionality."""

import ffmpeg
import socket
import threading
import time
from animutools.progress import (
    ProgressServer,
    _compile_ffmpeg_command,
    probe_duration,
    run_ffmpeg_with_progress,
)


class TestProbeData:
    """Tests for probe_duration function."""

    def test_probe_duration_from_format(self):
        """Test extracting duration from probe result."""
        probe_result = {"format": {"duration": "123.45"}}

        duration = probe_duration(probe_result)
        assert duration == 123.45

    def test_probe_duration_missing_format(self):
        """Test handling missing format in probe result."""
        probe_result = {}

        duration = probe_duration(probe_result)
        assert duration == 0

    def test_probe_duration_missing_duration(self):
        """Test handling missing duration in format."""
        probe_result = {"format": {}}

        duration = probe_duration(probe_result)
        assert duration == 0

    def test_probe_duration_invalid_value(self):
        """Test handling invalid duration value."""
        probe_result = {"format": {"duration": "not_a_number"}}

        duration = probe_duration(probe_result)
        assert duration == 0


class TestFFmpegCommand:
    """Tests for FFmpeg command preparation."""

    def test_global_progress_args_are_inserted_before_inputs(self):
        stream = (
            ffmpeg.input("input.mkv")
            .output("output.mp4")
            .global_args(
                "-progress",
                "tcp://127.0.0.1:1234",
                "-nostats",
                "-hide_banner",
            )
        )

        cmd = _compile_ffmpeg_command(stream, overwrite=True, progress=True)

        input_index = cmd.index("-i")
        output_index = cmd.index("output.mp4")

        assert cmd.index("-y") < input_index
        assert cmd.index("-hide_banner") < input_index
        assert cmd.index("-nostats") < input_index
        assert cmd.index("-progress") < input_index
        assert "-progress" not in cmd[output_index + 1 :]

    def test_run_captures_fast_loudnorm_stderr(
        self, fake_ffmpeg_env, sample_video_file, monkeypatch
    ):
        monkeypatch.setenv("FAKE_FFMPEG_DELAY", "0")
        stream = (
            ffmpeg.input(str(sample_video_file))["a:0"]
            .filter("loudnorm", print_format="json")
            .output("pipe:", format="null")
        )
        probe_result = {"format": {"duration": "10.0"}}

        stderr = run_ffmpeg_with_progress(
            stream,
            probe_result,
            description="Analyzing audio loudness",
            capture_stderr=True,
        )

        assert '"input_i"' in stderr


class TestProgressServer:
    """Tests for ProgressServer class."""

    def test_server_starts_and_stops(self):
        """Test that progress server can start and stop cleanly."""
        updates = []

        def callback(key, value):
            updates.append((key, value))

        server = ProgressServer(callback)
        url = server.start()

        # Should get a valid TCP URL
        assert url.startswith("tcp://127.0.0.1:")

        # Stop the server
        server.stop()

    def test_server_receives_progress_updates(self):
        """Test that server receives and processes progress updates."""
        updates = []
        received_event = threading.Event()

        def callback(key, value):
            updates.append((key, value))
            if key == "progress" and value == "end":
                received_event.set()

        server = ProgressServer(callback)
        url = server.start()

        # Extract host and port
        host_port = url.replace("tcp://", "")
        host, port = host_port.rsplit(":", 1)
        port = int(port)

        # Give server time to start accepting connections
        time.sleep(0.1)

        # Connect and send progress updates
        def send_updates():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))

            # Send some progress updates
            sock.sendall(b"frame=100\n")
            sock.sendall(b"out_time_ms=5000000\n")
            sock.sendall(b"progress=continue\n")

            time.sleep(0.05)

            sock.sendall(b"frame=200\n")
            sock.sendall(b"out_time_ms=10000000\n")
            sock.sendall(b"progress=end\n")

            sock.close()

        # Send updates in a thread
        sender = threading.Thread(target=send_updates, daemon=True)
        sender.start()

        # Wait for updates to be received
        received_event.wait(timeout=5)

        # Stop server
        server.stop()

        # Check that we received updates
        assert len(updates) > 0

        # Should have received connection notification
        assert ("start", "connected") in updates

        # Should have received frame updates
        frame_updates = [u for u in updates if u[0] == "frame"]
        assert len(frame_updates) > 0

        # Should have received time updates
        time_updates = [u for u in updates if u[0] == "out_time_ms"]
        assert len(time_updates) > 0

        # Should have received end marker
        assert ("progress", "end") in updates

    def test_server_handles_malformed_data(self):
        """Test that server handles malformed progress data gracefully."""
        updates = []

        def callback(key, value):
            updates.append((key, value))

        server = ProgressServer(callback)
        url = server.start()

        # Extract connection details
        host_port = url.replace("tcp://", "")
        host, port = host_port.rsplit(":", 1)
        port = int(port)

        time.sleep(0.1)

        # Send malformed data
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))

        # Send data without proper key=value format
        sock.sendall(b"not_valid_data\n")
        sock.sendall(b"also=missing=equals\n")
        sock.sendall(b"frame=100\n")  # This should work

        time.sleep(0.1)
        sock.close()

        # Stop server
        server.stop()

        # Should have received the valid update despite malformed data
        assert ("start", "connected") in updates
        frame_updates = [u for u in updates if u[0] == "frame"]
        assert len(frame_updates) > 0

    def test_server_connection_timeout(self):
        """Test that server handles connection timeouts."""
        updates = []

        def callback(key, value):
            updates.append((key, value))

        server = ProgressServer(callback)
        server.start()

        # Don't connect, just stop the server after a delay
        time.sleep(0.2)
        server.stop()

        # Server should stop cleanly even without connections
        # This test mainly checks that stop() doesn't hang
