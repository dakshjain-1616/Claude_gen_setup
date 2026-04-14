"""Tests for claudegen.voice module."""

import os
import tempfile
from pathlib import Path
import pytest
import wave
import struct

from claudegen.voice import VoiceTranscriber


class TestVoiceTranscriber:
    """Test cases for VoiceTranscriber class."""
    
    def test_model_loading(self):
        """Test that Whisper model loads successfully."""
        transcriber = VoiceTranscriber()
        assert transcriber.model is not None
    
    def test_transcribe_empty_audio(self):
        """Test transcription of non-speech audio."""
        # Create a simple sine wave (non-speech)
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "test.wav"
            
            # Generate a simple sine wave
            sample_rate = 16000
            duration = 1  # seconds
            frequency = 440  # Hz
            
            samples = []
            for i in range(int(sample_rate * duration)):
                value = int(32767 * 0.5 * ((i * frequency / sample_rate) % 1))
                samples.append(value)
            
            with wave.open(str(audio_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
            
            transcriber = VoiceTranscriber()
            result = transcriber.transcribe(str(audio_path))
            
            assert 'text' in result
            assert isinstance(result['text'], str)
    
    def test_transcribe_with_prompt(self):
        """Test transcription with prompt parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "test.wav"
            
            # Create a simple audio file
            sample_rate = 16000
            with wave.open(str(audio_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(struct.pack('<h', 0))
            
            transcriber = VoiceTranscriber()
            result = transcriber.transcribe_with_prompt(
                str(audio_path),
                prompt="Test prompt"
            )
            
            assert 'text' in result
            assert isinstance(result['text'], str)
    
    def test_transcribe_returns_dict(self):
        """Test that transcribe returns proper dict structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "test.wav"
            
            # Create minimal WAV file
            sample_rate = 16000
            with wave.open(str(audio_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(struct.pack('<h', 0))
            
            transcriber = VoiceTranscriber()
            result = transcriber.transcribe(str(audio_path))
            
            assert isinstance(result, dict)
            assert 'text' in result
            assert 'language' in result or result.get('language') is None


class TestAudioHandling:
    """Test audio file handling."""
    
    def test_wav_file_creation(self):
        """Test creating WAV files for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "test.wav"
            
            sample_rate = 16000
            with wave.open(str(audio_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(struct.pack('<h', 0))
            
            assert audio_path.exists()
            
            # Verify file can be read
            with wave.open(str(audio_path), 'rb') as wav_file:
                assert wav_file.getnchannels() == 1
                assert wav_file.getsampwidth() == 2
                assert wav_file.getframerate() == 16000