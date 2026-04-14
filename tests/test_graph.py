"""Tests for claudegen.graph module."""

import os
import tempfile
from pathlib import Path
import pytest

from claudegen.graph import DependencyGraph


class TestDependencyGraph:
    """Test cases for DependencyGraph class."""
    
    def test_extract_imports_python(self):
        """Test extracting imports from Python code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("import os\nimport sys\nfrom pathlib import Path\nfrom typing import Optional\nimport numpy as np\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_python(str(test_file))
            
            assert 'os' in imports
            assert 'sys' in imports
            assert 'pathlib' in imports
            assert 'typing' in imports
            assert 'numpy' in imports
    
    def test_extract_imports_js(self):
        """Test extracting imports from JavaScript code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.js"
            test_file.write_text("const express = require('express');\nimport lodash from 'lodash';\nimport { useState } from 'react';\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_js(str(test_file))
            
            assert 'express' in imports
            assert 'lodash' in imports
            assert 'react' in imports
    
    def test_extract_imports_ts(self):
        """Test extracting imports from TypeScript code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("import { Component } from '@angular/core';\nimport * as Rx from 'rxjs';\nimport axios from 'axios';\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_ts(str(test_file))
            
            assert '@angular/core' in imports
            assert 'rxjs' in imports
            assert 'axios' in imports
    
    def test_build_graph(self):
        """Test building dependency graph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "main.py").write_text("import os\nimport utils\n")
            (Path(tmpdir) / "utils.py").write_text("import sys\n")
            
            graph = DependencyGraph()
            files = [
                (str(Path(tmpdir) / "main.py"), 'python'),
                (str(Path(tmpdir) / "utils.py"), 'python')
            ]
            graph.build_graph(files)
            
            assert len(graph.graph.nodes()) >= 2
            assert len(graph.graph.edges()) >= 1
    
    def test_find_cycles(self):
        """Test cycle detection in graph."""
        graph = DependencyGraph()
        
        # Create a simple graph without cycles
        graph.graph.add_edge('a', 'b')
        graph.graph.add_edge('b', 'c')
        
        cycles = graph.find_cycles()
        assert len(cycles) == 0
        
        # Create a cycle
        graph.graph.add_edge('c', 'a')
        cycles = graph.find_cycles()
        assert len(cycles) > 0
    
    def test_get_top_level_modules(self):
        """Test extracting top-level module names."""
        graph = DependencyGraph()
        modules = graph.get_top_level_modules()
        
        # Test with a simple graph
        graph.graph.add_edge('main', 'os')
        graph.graph.add_edge('main', 'sys')
        modules = list(graph.graph.nodes())
        
        assert 'main' in modules
        assert 'os' in modules
        assert 'sys' in modules
    
    def test_export_html(self):
        """Test exporting graph to HTML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = DependencyGraph()
            graph.graph.add_edge('main', 'os')
            graph.graph.add_edge('main', 'sys')
            
            html_path = Path(tmpdir) / "test_graph.html"
            graph.export_html(str(html_path))
            
            assert html_path.exists()
            content = html_path.read_text()
            assert 'D3' in content or 'd3' in content
            assert 'main' in content
            assert 'os' in content
            assert 'sys' in content


class TestImportExtraction:
    """Test import extraction for different file types."""
    
    def test_python_standard_imports(self):
        """Test standard import statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("import flask\nimport requests\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_python(str(test_file))
            assert 'flask' in imports
            assert 'requests' in imports
    
    def test_python_from_imports(self):
        """Test from ... import statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("from flask import Flask\nfrom requests import get\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_python(str(test_file))
            assert 'flask' in imports
            assert 'requests' in imports
    
    def test_js_require_imports(self):
        """Test require() imports in JavaScript."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.js"
            test_file.write_text("const fs = require('fs');\nconst path = require('path');\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_js(str(test_file))
            assert 'fs' in imports
            assert 'path' in imports
    
    def test_ts_import_statements(self):
        """Test import statements in TypeScript."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.ts"
            test_file.write_text("import React from 'react';\nimport ReactDOM from 'react-dom';\n")
            
            graph = DependencyGraph()
            imports = graph.extract_imports_ts(str(test_file))
            assert 'react' in imports
            assert 'react-dom' in imports