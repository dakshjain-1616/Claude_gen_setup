"""Voice transcription module using faster-whisper."""

from pathlib import Path
from typing import Dict, Optional


class VoiceTranscriber:
    """Transcribes audio files to text using faster-whisper (runs locally on CPU)."""

    def __init__(self, model_size: str = "base.en"):
        """Initialize the transcriber and load the Whisper model.

        Args:
            model_size: Whisper model size. 'base.en' is fast and accurate for English.
        """
        from faster_whisper import WhisperModel
        self.model_size = model_size
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str) -> Dict:
        """Transcribe an audio file.

        Args:
            audio_path: Path to a WAV, MP3, or other audio file.

        Returns:
            Dict with keys: 'text' (full transcript), 'segments' (list of segment dicts),
            'language' (detected language code).
        """
        segments, info = self.model.transcribe(audio_path)
        segment_list = []
        full_text_parts = []
        for seg in segments:
            segment_list.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })
            full_text_parts.append(seg.text.strip())

        return {
            "text": " ".join(full_text_parts),
            "segments": segment_list,
            "language": getattr(info, "language", None),
        }

    def transcribe_with_prompt(self, audio_path: str, prompt: str = "") -> Dict:
        """Transcribe with an initial prompt to guide the model.

        Args:
            audio_path: Path to the audio file.
            prompt: Text prompt to condition the transcription (e.g. domain-specific terms).

        Returns:
            Same structure as transcribe().
        """
        segments, info = self.model.transcribe(audio_path, initial_prompt=prompt or None)
        segment_list = []
        full_text_parts = []
        for seg in segments:
            segment_list.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })
            full_text_parts.append(seg.text.strip())

        return {
            "text": " ".join(full_text_parts),
            "segments": segment_list,
            "language": getattr(info, "language", None),
        }
