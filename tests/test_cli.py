"""Tests for CLI argument parsing and command-line interface."""

import pytest
from animutools.cli import parse_args


class TestArgParsing:
    """Tests for command-line argument parsing."""

    def test_basic_args(self, monkeypatch):
        """Test parsing basic input and output arguments."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4'])
        args = parse_args()

        assert args.infile == 'input.mkv'
        assert args.outfile == 'output.mp4'
        assert args.bulk is False
        assert args.hls is False

    def test_scale_argument(self, monkeypatch):
        """Test parsing --scale argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--scale', '1280:720'])
        args = parse_args()

        assert args.scale == '1280:720'

    def test_hls_argument(self, monkeypatch):
        """Test parsing --hls argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.m3u8', '--hls'])
        args = parse_args()

        assert args.hls is True
        assert args.hls_time == 4  # Default value

    def test_hls_custom_time(self, monkeypatch):
        """Test parsing --hls_time argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.m3u8', '--hls', '--hls_time', '6'])
        args = parse_args()

        assert args.hls is True
        assert args.hls_time == 6.0

    def test_bulk_mode(self, monkeypatch):
        """Test parsing --bulk argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'videos/', 'ep{num}.mkv', '--bulk'])
        args = parse_args()

        assert args.bulk is True
        assert args.infile == 'videos/'
        assert args.outfile == 'ep{num}.mkv'

    def test_subtitle_index(self, monkeypatch):
        """Test parsing --subtitle_index argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--subtitle_index', '2'])
        args = parse_args()

        assert args.subtitle_index == 2

    def test_target_bitrate(self, monkeypatch):
        """Test parsing --target_bitrate argument."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--target_bitrate', '5000'])
        args = parse_args()

        assert args.target_bitrate == 5000

    def test_letterbox_flag(self, monkeypatch):
        """Test parsing --letterbox flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--letterbox'])
        args = parse_args()

        assert args.letterbox is True

    def test_test_mode(self, monkeypatch):
        """Test parsing --test flag (encodes only first 60 seconds)."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--test'])
        args = parse_args()

        assert args.test is True

    def test_dry_run(self, monkeypatch):
        """Test parsing --dry_run flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--dry_run'])
        args = parse_args()

        assert args.dry_run is True

    def test_probe_flag(self, monkeypatch):
        """Test parsing --probe flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--probe'])
        args = parse_args()

        assert args.probe is True

    def test_no_progress_flag(self, monkeypatch):
        """Test parsing --no-progress flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '--no-progress'])
        args = parse_args()

        assert args.no_progress is True

    def test_overwrite_flag(self, monkeypatch):
        """Test parsing --overwrite/-y flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '-y'])
        args = parse_args()

        assert args.overwrite is True

    def test_verbose_flag(self, monkeypatch):
        """Test parsing --verbose/-v flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '-v'])
        args = parse_args()

        assert args.verbose is True

    def test_quiet_flag(self, monkeypatch):
        """Test parsing --quiet/-q flag."""
        monkeypatch.setattr('sys.argv', ['fenc', 'input.mkv', 'output.mp4', '-q'])
        args = parse_args()

        assert args.quiet is True
