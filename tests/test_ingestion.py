"""Tests for claudegen.ingestion module."""

import os
import tempfile
from pathlib import Path
import pytest

from claudegen.ingestion import RepoIngester, FileInfo, ManifestInfo


class TestRepoIngester:
    """Test cases for RepoIngester class."""
    
    def test_scan_python_file(self):
        """Test scanning a Python file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test Python file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("import os\nimport sys\n\ndef main():\n    pass\n")
            
            ingester = RepoIngester(str(tmpdir))
            result = ingester.scan(max_files=10)
            
            assert result['file_count'] == 1
            assert 'python' in result['languages']
            assert len(ingester.files) == 1
            assert ingester.files[0].language == 'python'
    
    def test_scan_multiple_files(self):
        """Test scanning multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple test files
            (Path(tmpdir) / "test1.py").write_text("import os\n")
            (Path(tmpdir) / "test2.py").write_text("import sys\n")
            (Path(tmpdir) / "test3.js").write_text("const x = 1;\n")
            
            ingester = RepoIngester(str(tmpdir))
            result = ingester.scan(max_files=10)
            
            assert result['file_count'] == 3
            assert 'python' in result['languages']
            assert 'javascript' in result['languages']
    
    def test_get_file_info(self):
        """Test FileInfo extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "example.py"
            content = "line1\nline2\nline3\n"
            test_file.write_text(content)
            
            ingester = RepoIngester(str(tmpdir))
            info = ingester._get_file_info(test_file)
            
            assert info.path == "example.py"
            assert info.language == 'python'
            assert info.lines == 3
            assert info.size == len(content.encode('utf-8'))
    
    def test_scan_with_max_files_limit(self):
        """Test max_files parameter limits scanning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10 files
            for i in range(10):
                (Path(tmpdir) / f"file{i}.py").write_text(f"# {i}\n")
            
            ingester = RepoIngester(str(tmpdir))
            result = ingester.scan(max_files=5)
            
            assert result['file_count'] <= 5
            assert len(ingester.files) <= 5
    
    def test_get_files_by_language(self):
        """Test filtering files by language."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "py1.py").write_text("# python\n")
            (Path(tmpdir) / "py2.py").write_text("# python\n")
            (Path(tmpdir) / "js1.js").write_text("// js\n")
            
            ingester = RepoIngester(str(tmpdir))
            ingester.scan(max_files=10)
            
            python_files = ingester.get_files_by_language('python')
            js_files = ingester.get_files_by_language('javascript')
            
            assert len(python_files) == 2
            assert len(js_files) == 1


class TestManifestParsing:
    """Test manifest parsing functionality."""
    
    def test_parse_requirements_txt(self):
        """Test parsing requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req_file = Path(tmpdir) / "requirements.txt"
            req_file.write_text("numpy>=1.20\npandas==1.3.0\nrequests\n")
            
            ingester = RepoIngester(str(tmpdir))
            deps = ingester._parse_requirements(req_file)
            
            assert 'numpy' in deps
            assert 'pandas' in deps
            assert 'requests' in deps
    
    def test_parse_pyproject_toml(self):
        """Test parsing pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "test"\ndependencies = ["click", "pydantic"]\n'
            )
            
            ingester = RepoIngester(str(tmpdir))
            deps = ingester._parse_pyproject(pyproject)
            
            assert 'click' in deps
            assert 'pydantic' in deps
    
    def test_parse_package_json(self):
        """Test parsing package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = Path(tmpdir) / "package.json"
            pkg_json.write_text(
                '{"name": "test", "dependencies": {"express": "^4.0", "lodash": "^4.0"}}'
            )
            
            ingester = RepoIngester(str(tmpdir))
            deps = ingester._parse_package_json(pkg_json)
            
            assert 'express' in deps
            assert 'lodash' in deps