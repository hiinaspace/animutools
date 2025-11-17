# animutools Test Suite

This directory contains automated tests for the animutools ffmpeg wrapper.

## Overview

The test suite uses a **fake ffmpeg implementation** to test the wrapper without requiring actual video encoding. This approach provides:

- **Fast execution** (~12 seconds for full suite)
- **Deterministic behavior** (no flaky tests from encoding variability)
- **Isolation** (tests don't depend on ffmpeg installation or version)
- **Comprehensive coverage** of command generation, progress tracking, and error handling

## Running Tests

### Install Test Dependencies

```bash
# Create and activate virtual environment (if not already done)
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install package with test dependencies
uv pip install -e ".[dev]"
```

### Run All Tests

```bash
pytest tests/
```

### Run Specific Test Files

```bash
pytest tests/test_core.py        # Core video processing tests
pytest tests/test_cli.py         # CLI argument parsing tests
pytest tests/test_progress.py    # Progress tracking tests
```

### Run with Coverage

```bash
pytest tests/ --cov=animutools --cov-report=html
```

Then open `htmlcov/index.html` to view the coverage report.

### Run with Verbose Output

```bash
pytest tests/ -v
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                  # Pytest fixtures and configuration
├── fake_ffmpeg/
│   ├── __init__.py
│   └── fake_ffmpeg.py          # Fake ffmpeg/ffprobe implementation
├── fixtures/                    # Test data fixtures (currently empty, uses defaults)
├── test_cli.py                 # CLI argument parsing tests (15 tests)
├── test_core.py                # Core functionality tests (10 tests)
├── test_progress.py            # Progress tracking tests (8 tests)
└── README.md                   # This file
```

## Fake FFmpeg Implementation

The `fake_ffmpeg/fake_ffmpeg.py` script simulates ffmpeg and ffprobe behavior:

### Features

1. **Dual Mode Operation**
   - Invoked as `ffprobe`: Returns JSON probe data
   - Invoked as `ffmpeg`: Simulates encoding with progress reporting

2. **Progress Protocol**
   - Connects to `-progress tcp://...` socket
   - Sends realistic progress updates (frame count, timestamps)
   - Respects configurable timing via environment variables

3. **Loudnorm Simulation**
   - Detects loudnorm analysis pass (JSON format to stderr)
   - Returns fake but realistic loudnorm measurements

4. **Output File Creation**
   - Creates output files (regular files or HLS playlists with segments)
   - Handles directory creation for HLS segment files

### Configuration via Environment Variables

The fake ffmpeg behavior can be customized:

```bash
FAKE_FFMPEG_DURATION=10.0       # Video duration in seconds (default: 10.0)
FAKE_FFMPEG_DELAY=0.01          # Delay between updates (default: 0.01)
FAKE_FFMPEG_UPDATE_FREQ=0.5     # Seconds per progress update (default: 0.5)
FAKE_FFMPEG_EXIT_CODE=0         # Exit code to return (default: 0)
FAKE_FFMPEG_PROBE_FIXTURE=/path # Custom probe JSON file (optional)
```

Example with custom settings:

```bash
FAKE_FFMPEG_DURATION=5.0 pytest tests/test_core.py -v
```

## Test Coverage

### test_cli.py - CLI Argument Parsing (15 tests)

Tests command-line argument parsing for all flags:
- Basic input/output arguments
- Encoding options (`--scale`, `--letterbox`, `--target_bitrate`)
- HLS options (`--hls`, `--hls_time`)
- Subtitle options (`--subtitle_index`, `--subtitle_file`)
- Modes (`--bulk`, `--test`, `--dry_run`, `--probe`)
- Flags (`--overwrite`, `--verbose`, `--quiet`, `--no-progress`)

### test_core.py - Core Functionality (10 tests)

Tests the main video processing pipeline:

**Probe Tests** (4 tests)
- Basic probe data extraction
- Japanese audio track selection
- English subtitle track selection
- Duration extraction

**Loudnorm Tests** (2 tests)
- Loudnorm analysis success
- Measurement format validation

**Process Video Tests** (4 tests)
- Basic encoding with output file creation
- Encoding with `--scale` flag
- HLS output with playlist and segments
- Encoding with progress tracking enabled

### test_progress.py - Progress Tracking (8 tests)

Tests the TCP progress server and related utilities:

**Probe Duration Tests** (4 tests)
- Duration extraction from probe data
- Handling missing format/duration fields
- Handling invalid duration values

**Progress Server Tests** (4 tests)
- Server start/stop lifecycle
- Receiving and processing progress updates
- Handling malformed data gracefully
- Connection timeout handling

## Writing New Tests

### Using Fixtures

The test suite provides several fixtures (defined in `conftest.py`):

```python
def test_example(fake_ffmpeg_env, sample_video_file, output_file):
    """Example test using fixtures."""
    # fake_ffmpeg_env: Sets up PATH to use fake ffmpeg
    # sample_video_file: Path to a temporary test video file
    # output_file: Path for output file (in tmp_path)

    # Your test code here
    process_video(str(sample_video_file), str(output_file), args)
    assert output_file.exists()
```

### Testing with Custom Probe Data

Create a custom probe fixture:

```python
import json
from pathlib import Path

def test_with_custom_probe(fake_ffmpeg_env, tmp_path, monkeypatch):
    # Create custom probe JSON
    probe_data = {"streams": [...], "format": {...}}
    fixture_file = tmp_path / "probe.json"
    fixture_file.write_text(json.dumps(probe_data))

    # Tell fake_ffmpeg to use it
    monkeypatch.setenv("FAKE_FFMPEG_PROBE_FIXTURE", str(fixture_file))

    # Run your test
    ...
```

### Testing Error Cases

Configure fake ffmpeg to fail:

```python
def test_encoding_failure(fake_ffmpeg_env, monkeypatch):
    # Make fake ffmpeg exit with error code 1
    monkeypatch.setenv("FAKE_FFMPEG_EXIT_CODE", "1")

    # Test that your code handles the error
    with pytest.raises(RuntimeError):
        process_video(...)
```

## Design Philosophy

The test suite follows these principles:

1. **Fast Iteration**: Tests run in seconds, not minutes
2. **Happy Path Focus**: Initial tests cover the most common use cases
3. **Realistic but Fake**: Simulates real ffmpeg behavior without actual encoding
4. **Maintainable**: Clear test names, minimal mocking, straightforward fixtures
5. **Isolated**: Each test is independent and uses temporary files

## Future Enhancements

Potential areas for expansion:

- [ ] Bulk processing tests (requires test file creation logic)
- [ ] Error handling tests (ffmpeg failures, invalid inputs)
- [ ] Integration tests with real ffmpeg (optional, for CI)
- [ ] Performance benchmarks
- [ ] Additional edge cases (unusual video formats, missing streams)

## Troubleshooting

### Tests hang or timeout

Check that the progress server is properly stopped. The tests use threading for the TCP server, and improper cleanup can cause hangs.

### Fake ffmpeg not found

Ensure the `fake_ffmpeg_env` fixture is included in your test function signature. This fixture sets up the PATH automatically.

### Tests fail on Windows

The fake ffmpeg script uses symlinks on Unix systems. On Windows, it copies the script instead. Ensure the script is executable and Python can run it.

## Contributing

When adding new tests:

1. Follow existing naming conventions (`test_<feature>_<scenario>`)
2. Use descriptive test names that explain what's being tested
3. Keep tests focused on a single behavior
4. Use fixtures for common setup
5. Run the full suite before committing: `pytest tests/`
