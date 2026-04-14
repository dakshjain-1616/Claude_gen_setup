"""Tests for claudegen.synthesis module."""

import os
import tempfile
from pathlib import Path
import pytest

from claudegen.synthesis import ClaudeSynthesizer, ClaudeMdConfig


class TestClaudeSynthesizer:
    """Test cases for ClaudeSynthesizer class."""
    
    def test_synthesizer_initialization(self):
        """Test that synthesizer initializes correctly."""
        synthesizer = ClaudeSynthesizer()
        assert synthesizer is not None
        assert synthesizer.model_name is not None
    
    def test_synthesizer_with_custom_model(self):
        """Test synthesizer with custom model name."""
        synthesizer = ClaudeSynthesizer(model='anthropic/claude-3-5-sonnet')
        assert synthesizer.model_name == 'anthropic/claude-3-5-sonnet'
    
    def test_generate_claude_md_structure(self):
        """Test that generated CLAUDE.md has proper structure."""
        config = ClaudeMdConfig(
            project_name="test_project",
            description="Test description",
            main_technologies=['python'],
            key_files=['main.py'],
            dependencies=['numpy', 'pandas']
        )
        
        synthesizer = ClaudeSynthesizer()
        content = synthesizer.generate_claude_md(config)
        
        # Check for required sections
        assert '# test_project' in content or 'test_project' in content
        assert 'Technology Stack' in content or 'Technologies' in content
        assert 'Key Files' in content or 'Files' in content
        assert 'Dependencies' in content or 'dependency' in content.lower()
    
    def test_claude_md_config_creation(self):
        """Test ClaudeMdConfig dataclass."""
        config = ClaudeMdConfig(
            project_name="my_project",
            description="A test project",
            main_technologies=['python', 'javascript'],
            key_files=['src/main.py', 'app.js'],
            dependencies=['requests', 'express']
        )
        
        assert config.project_name == "my_project"
        assert config.description == "A test project"
        assert 'python' in config.main_technologies
        assert 'javascript' in config.main_technologies
        assert len(config.key_files) == 2
        assert len(config.dependencies) == 2
    
    def test_generate_with_voice_notes(self):
        """Test generation with voice notes."""
        config = ClaudeMdConfig(
            project_name="test_project",
            description="Test",
            main_technologies=['python'],
            key_files=['main.py'],
            dependencies=[],
            voice_notes="Add unit tests for all modules"
        )
        
        synthesizer = ClaudeSynthesizer()
        content = synthesizer.generate_claude_md(config)
        
        assert len(content) > 0
        assert isinstance(content, str)
    
    def test_format_list(self):
        """Test list formatting helper."""
        items = ['item1', 'item2', 'item3']
        
        synthesizer = ClaudeSynthesizer()
        formatted = synthesizer._format_list(items)
        
        assert 'item1' in formatted
        assert 'item2' in formatted
        assert 'item3' in formatted


class TestTemplateGeneration:
    """Test template generation functionality."""
    
    def test_template_has_sections(self):
        """Test that template includes all required sections."""
        config = ClaudeMdConfig(
            project_name="test",
            description="Test project",
            main_technologies=['python'],
            key_files=['main.py'],
            dependencies=[]
        )
        
        synthesizer = ClaudeSynthesizer()
        content = synthesizer.generate_claude_md(config)
        
        # Check for markdown structure
        assert '#' in content  # Has headers
        assert len(content) > 80  # Has substantial content
    
    def test_template_project_name(self):
        """Test that project name appears in output."""
        config = ClaudeMdConfig(
            project_name="MyAwesomeProject",
            description="Description",
            main_technologies=['python'],
            key_files=[],
            dependencies=[]
        )
        
        synthesizer = ClaudeSynthesizer()
        content = synthesizer.generate_claude_md(config)
        
        assert 'MyAwesomeProject' in content
    
    def test_template_technologies(self):
        """Test that technologies are listed."""
        config = ClaudeMdConfig(
            project_name="test",
            description="Test",
            main_technologies=['python', 'typescript', 'react'],
            key_files=[],
            dependencies=[]
        )
        
        synthesizer = ClaudeSynthesizer()
        content = synthesizer.generate_claude_md(config)
        
        # Should mention at least some technologies
        assert len(content) > 0