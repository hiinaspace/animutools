"""
Making core functionality accessible at package level
"""

from .core import process_video
from .cli import main
from rich.console import Console

__version__ = "0.1.0"
__all__ = ["process_video", "main"]

console = Console()
