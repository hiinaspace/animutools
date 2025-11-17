"""Tests for core video processing functionality."""

import pytest
from pathlib import Path
from animutools.core import probe_video, analyze_audio_loudness, process_video


class TestProbeVideo:
    """Tests for probe_video function."""

    def test_probe_video_basic(self, fake_ffmpeg_env, sample_video_file):
        """Test that probe_video returns expected stream information."""
        result = probe_video(str(sample_video_file))

        # Check that we got the expected keys
        assert "probe" in result
        assert "audio_track" in result
        assert "audio_stream" in result
        assert "sub_track" in result
        assert "sub_type" in result

        # Verify probe data structure
        probe = result["probe"]
        assert "streams" in probe
        assert "format" in probe

        # Should have video, audio, and subtitle streams
        streams = probe["streams"]
        assert len(streams) >= 3

        # Check stream types
        stream_types = [s["codec_type"] for s in streams]
        assert "video" in stream_types
        assert "audio" in stream_types
        assert "subtitle" in stream_types

    def test_probe_video_selects_japanese_audio(self, fake_ffmpeg_env, sample_video_file):
        """Test that probe_video correctly selects Japanese audio track."""
        result = probe_video(str(sample_video_file))

        # The default fake data has Japanese audio on track 1 (index 1)
        audio_stream = result["audio_stream"]
        assert audio_stream is not None
        assert audio_stream["codec_type"] == "audio"

        # Check that it selected the Japanese track
        if "tags" in audio_stream and "language" in audio_stream["tags"]:
            assert audio_stream["tags"]["language"] == "jpn"

    def test_probe_video_selects_english_subtitle(self, fake_ffmpeg_env, sample_video_file):
        """Test that probe_video correctly selects English subtitle track."""
        result = probe_video(str(sample_video_file))

        # Should select English subtitle track
        sub_track = result["sub_track"]
        assert sub_track is not None

        # Verify it's text subtitles (not DVD/PGS)
        assert result["sub_type"] == "text"

    def test_probe_video_gets_duration(self, fake_ffmpeg_env, sample_video_file):
        """Test that probe_video extracts duration from format."""
        result = probe_video(str(sample_video_file))

        probe = result["probe"]
        duration = float(probe["format"]["duration"])

        # Should match the fake duration (default 10.0 seconds)
        assert duration > 0
        assert duration == 10.0


class TestAnalyzeAudioLoudness:
    """Tests for analyze_audio_loudness function."""

    def test_loudnorm_analysis_success(self, fake_ffmpeg_env, sample_video_file):
        """Test that loudnorm analysis returns measurements."""
        # First probe the video to get stream info
        video_info = probe_video(str(sample_video_file))

        # Run loudnorm analysis
        measurements, sample_rate = analyze_audio_loudness(
            str(sample_video_file),
            video_info["audio_track"],
            video_info["audio_stream"],
            video_info["probe"]
        )

        # Should get measurements back
        assert measurements is not None
        assert sample_rate is not None

        # Check expected loudnorm fields
        assert "input_i" in measurements
        assert "input_tp" in measurements
        assert "input_lra" in measurements
        assert "input_thresh" in measurements

        # Sample rate should be extracted from audio stream
        assert sample_rate == "48000"

    def test_loudnorm_measurements_format(self, fake_ffmpeg_env, sample_video_file):
        """Test that loudnorm measurements are in expected format."""
        video_info = probe_video(str(sample_video_file))

        measurements, _ = analyze_audio_loudness(
            str(sample_video_file),
            video_info["audio_track"],
            video_info["audio_stream"],
            video_info["probe"]
        )

        # Values should be string representations of numbers
        assert measurements is not None
        input_lufs = float(measurements["input_i"])
        assert input_lufs < 0  # LUFS values are negative

        # Check reasonable ranges
        assert -30 < input_lufs < 0


class TestProcessVideo:
    """Tests for full video processing pipeline."""

    def test_process_video_creates_output(self, fake_ffmpeg_env, sample_video_file, output_file):
        """Test that process_video creates an output file."""
        # Create a minimal args object
        class Args:
            subtitle_index = None
            subtitle_file = None
            scale = None
            letterbox = False
            target_bitrate = 10000
            buffer_duration = 1
            hls = False
            hls_time = 4
            dry_run = False
            remux = False
            probe = False
            no_progress = True  # Disable progress for simpler test
            test = False
            overwrite = True
            verbose = False

        args = Args()

        # Process the video
        result = process_video(str(sample_video_file), str(output_file), args)

        # Should return True on success
        assert result is True

        # Output file should exist
        assert output_file.exists()

    def test_process_video_with_scale(self, fake_ffmpeg_env, sample_video_file, output_file):
        """Test that process_video handles --scale flag."""
        class Args:
            subtitle_index = None
            subtitle_file = None
            scale = "1280:720"  # Scale to 720p
            letterbox = False
            target_bitrate = 10000
            buffer_duration = 1
            hls = False
            hls_time = 4
            dry_run = False
            remux = False
            probe = False
            no_progress = True
            test = False
            overwrite = True
            verbose = False

        args = Args()

        result = process_video(str(sample_video_file), str(output_file), args)

        assert result is True
        assert output_file.exists()

    def test_process_video_hls_output(self, fake_ffmpeg_env, sample_video_file, tmp_path):
        """Test that process_video creates HLS output correctly."""
        output_m3u8 = tmp_path / "output.m3u8"

        class Args:
            subtitle_index = None
            subtitle_file = None
            scale = None
            letterbox = False
            target_bitrate = 10000
            buffer_duration = 1
            hls = True
            hls_time = 4
            dry_run = False
            remux = False
            probe = False
            no_progress = True
            test = False
            overwrite = True
            verbose = False

        args = Args()

        result = process_video(str(sample_video_file), str(output_m3u8), args)

        assert result is True

        # Should create m3u8 playlist
        assert output_m3u8.exists()

        # Should create segment directory
        segment_dir = tmp_path / "output.m3u8.ts"
        assert segment_dir.exists()
        assert segment_dir.is_dir()

        # Should have segment files
        segments = list(segment_dir.glob("*.ts"))
        assert len(segments) > 0

    def test_process_video_with_progress(self, fake_ffmpeg_env, sample_video_file, output_file):
        """Test that process_video works with progress tracking enabled."""
        class Args:
            subtitle_index = None
            subtitle_file = None
            scale = None
            letterbox = False
            target_bitrate = 10000
            buffer_duration = 1
            hls = False
            hls_time = 4
            dry_run = False
            remux = False
            probe = False
            no_progress = False  # Enable progress tracking
            test = False
            overwrite = True
            verbose = False

        args = Args()

        # This should complete without hanging
        result = process_video(str(sample_video_file), str(output_file), args)

        assert result is True
        assert output_file.exists()
