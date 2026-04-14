"""ClaudeGen - Generate CLAUDE.md files using repo scanning, dependency graph analysis, and voice input."""

__version__ = "0.1.0"
__author__ = "ClaudeGen Team"

from claudegen.ingestion import RepoIngester
from claudegen.graph import DependencyGraph
from claudegen.synthesis import ClaudeSynthesizer, ClaudeMdConfig

# VoiceTranscriber is lazily imported because faster-whisper loads a model
# at construction time — importing the module itself is always safe.
from claudegen.voice import VoiceTranscriber

__all__ = [
    "RepoIngester",
    "DependencyGraph",
    "VoiceTranscriber",
    "ClaudeSynthesizer",
    "ClaudeMdConfig",
    "__version__",
]