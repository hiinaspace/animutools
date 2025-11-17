"""Pytest configuration and fixtures for animutools tests."""

import os
import sys
from pathlib import Path
import pytest


@pytest.fixture(scope="session")
def fake_ffmpeg_bin(tmp_path_factory):
    """
    Create a temporary directory with fake ffmpeg and ffprobe executables.

    This fixture creates symlinks to our fake_ffmpeg.py script named
    'ffmpeg' and 'ffprobe', allowing tests to use them transparently.
    """
    # Create a temporary bin directory
    bin_dir = tmp_path_factory.mktemp("bin")

    # Path to our fake_ffmpeg.py script
    fake_script = Path(__file__).parent / "fake_ffmpeg" / "fake_ffmpeg.py"
    assert fake_script.exists(), f"fake_ffmpeg.py not found at {fake_script}"

    # Create symlinks for ffmpeg and ffprobe
    ffmpeg_link = bin_dir / "ffmpeg"
    ffprobe_link = bin_dir / "ffprobe"

    # On Unix systems, create symlinks
    if os.name == "posix":
        ffmpeg_link.symlink_to(fake_script)
        ffprobe_link.symlink_to(fake_script)
    else:
        # On Windows, copy the script
        import shutil
        shutil.copy(fake_script, ffmpeg_link.with_suffix(".py"))
        shutil.copy(fake_script, ffprobe_link.with_suffix(".py"))

    return bin_dir


@pytest.fixture
def fake_ffmpeg_env(fake_ffmpeg_bin, monkeypatch):
    """
    Set up environment to use fake ffmpeg/ffprobe.

    This fixture modifies the PATH so that our fake executables are found
    first, and provides a clean environment for each test.
    """
    # Prepend our bin directory to PATH
    original_path = os.environ.get("PATH", "")
    new_path = f"{fake_ffmpeg_bin}{os.pathsep}{original_path}"
    monkeypatch.setenv("PATH", new_path)

    # Set default environment variables for fake ffmpeg
    # These can be overridden in individual tests
    monkeypatch.setenv("FAKE_FFMPEG_DURATION", "10.0")
    monkeypatch.setenv("FAKE_FFMPEG_DELAY", "0.01")
    monkeypatch.setenv("FAKE_FFMPEG_UPDATE_FREQ", "0.5")
    monkeypatch.setenv("FAKE_FFMPEG_EXIT_CODE", "0")

    return {
        "bin_dir": fake_ffmpeg_bin,
        "path": new_path,
    }


@pytest.fixture
def sample_video_file(tmp_path):
    """
    Create a sample video file for testing.

    This just creates an empty file with a .mkv extension.
    The fake ffmpeg will handle it appropriately.
    """
    video_file = tmp_path / "input.mkv"
    video_file.write_bytes(b"fake video data")
    return video_file


@pytest.fixture
def output_file(tmp_path):
    """Return path for output file."""
    return tmp_path / "output.mp4"


@pytest.fixture
def sample_probe_data():
    """Return sample ffprobe JSON data."""
    return {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "duration": "10.0"
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
            "filename": "input.mkv",
            "format_name": "matroska,webm",
            "format_long_name": "Matroska / WebM",
            "duration": "10.0",
            "size": "104857600",
            "bit_rate": "8388608"
        }
    }
