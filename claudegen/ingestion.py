"""Repository ingestion module — scans codebases, parses manifests, detects frameworks."""

import json
import re
import tomllib
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class FileInfo:
    """Information about a scanned source file."""
    path: str      # relative to repo root
    language: str
    size: int
    lines: int


@dataclass
class ManifestInfo:
    """Information extracted from a manifest file (package.json, pyproject.toml, etc.)."""
    type: str              # "pip" | "npm" | "cargo" | "go"
    dependencies: List[str]
    metadata: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

LANGUAGE_MAP: Dict[str, str] = {
    ".py":  "python",
    ".js":  "javascript",
    ".ts":  "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

SKIP_DIRS: Set[str] = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".cache",
    ".tox", "eggs", ".eggs", "htmlcov",
}

ENTRY_POINT_NAMES: List[str] = [
    "main.py", "app.py", "server.py", "run.py", "index.py", "wsgi.py", "asgi.py",
    "index.ts", "index.js", "server.ts", "server.js", "app.ts", "app.js",
    "cmd/main.go",
]

FRAMEWORK_MARKERS: Dict[str, str] = {
    "fastapi":       "FastAPI",
    "flask":         "Flask",
    "django":        "Django",
    "starlette":     "Starlette",
    "tornado":       "Tornado",
    "aiohttp":       "aiohttp",
    "litestar":      "Litestar",
    "next":          "Next.js",
    "nextjs":        "Next.js",
    "@next/core":    "Next.js",
    "react":         "React",
    "vue":           "Vue",
    "@angular/core": "Angular",
    "express":       "Express",
    "nestjs":        "NestJS",
    "@nestjs/core":  "NestJS",
    "svelte":        "Svelte",
    "nuxt":          "Nuxt",
}


class RepoIngester:
    """Scans a repository and extracts structured metadata."""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.files: List[FileInfo] = []
        self.manifests: List[ManifestInfo] = []
        self.languages: Set[str] = set()
        self.frameworks: List[str] = []
        self.entry_points: List[str] = []
        self.readme_content: str = ""
        self._gitignore_fn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, max_files: int = 1000) -> Dict:
        """Scan the repository.  Returns a summary dict."""
        self.files = []
        self.manifests = []
        self.languages = set()
        self.frameworks = []
        self.entry_points = []
        self.readme_content = ""

        # Load .gitignore if present
        self._gitignore_fn = self._load_gitignore()

        # Collect manifests at the repo root (non-code files)
        for name in ["requirements.txt", "pyproject.toml", "package.json",
                     "setup.py", "go.mod", "Cargo.toml"]:
            p = self.root_path / name
            if p.exists():
                info = self._check_manifest(p)
                if info:
                    self.manifests.append(info)

        # Detect README
        self.readme_content = self._read_readme()

        # Walk source files
        file_count = 0
        for path in self._walk(self.root_path):
            if file_count >= max_files:
                break
            if path.is_file() and path.suffix.lower() in LANGUAGE_MAP:
                self.files.append(self._get_file_info(path))
                self.languages.add(LANGUAGE_MAP[path.suffix.lower()])
                file_count += 1

        # Detect entry points
        self.entry_points = self._detect_entry_points()

        # Detect frameworks from manifest deps
        self.frameworks = self._detect_frameworks()

        return {
            "root_path":      str(self.root_path),
            "file_count":     len(self.files),
            "manifest_count": len(self.manifests),
            "languages":      list(self.languages),
            "frameworks":     self.frameworks,
            "entry_points":   self.entry_points,
            "readme_snippet": self.readme_content[:300] if self.readme_content else "",
            "total_size":     sum(f.size for f in self.files),
        }

    def get_file_content(self, file_path: str) -> str:
        """Return content of a file relative to the repo root."""
        try:
            return (self.root_path / file_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def get_files_by_language(self, language: str) -> List[FileInfo]:
        return [f for f in self.files if f.language == language]

    # ------------------------------------------------------------------
    # Walking & gitignore
    # ------------------------------------------------------------------

    def _load_gitignore(self):
        try:
            from gitignore_parser import parse_gitignore
            gp = self.root_path / ".gitignore"
            if gp.exists():
                return parse_gitignore(str(gp))
        except ImportError:
            pass
        return None

    def _walk(self, root: Path):
        """Yield files, respecting SKIP_DIRS and .gitignore."""
        try:
            entries = sorted(root.iterdir())
        except PermissionError:
            return
        for item in entries:
            if self._gitignore_fn and self._gitignore_fn(str(item)):
                continue
            if item.is_dir():
                if item.name in SKIP_DIRS or item.name.startswith("."):
                    continue
                yield from self._walk(item)
            else:
                yield item

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_entry_points(self) -> List[str]:
        entry_points = []
        # Check root
        for name in ENTRY_POINT_NAMES:
            if (self.root_path / name).exists():
                entry_points.append(name)
        # Check every first-level subdirectory (covers src/, app/, taskapi/, etc.)
        try:
            for subdir in sorted(self.root_path.iterdir()):
                if not subdir.is_dir():
                    continue
                if subdir.name in SKIP_DIRS or subdir.name.startswith("."):
                    continue
                for name in ENTRY_POINT_NAMES:
                    if (subdir / name).exists():
                        entry_points.append(f"{subdir.name}/{name}")
        except PermissionError:
            pass
        return entry_points

    def _detect_frameworks(self) -> List[str]:
        found: List[str] = []
        seen: Set[str] = set()
        all_deps: List[str] = []
        for m in self.manifests:
            all_deps.extend(m.dependencies)
        for dep in all_deps:
            dl = dep.lower().lstrip("@")
            for marker, name in FRAMEWORK_MARKERS.items():
                if marker.lstrip("@") in dl and name not in seen:
                    found.append(name)
                    seen.add(name)
        return found

    def _read_readme(self) -> str:
        for name in ["README.md", "README.rst", "README.txt", "README"]:
            p = self.root_path / name
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
        return ""

    def project_name(self) -> str:
        """Return the canonical project name from the manifest, or the directory name."""
        # pyproject.toml [project] name
        pyproject = self.root_path / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                name = data.get("project", {}).get("name", "")
                if name:
                    return name
            except Exception:
                pass
        # package.json name
        pkg_json = self.root_path / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                name = data.get("name", "")
                if name:
                    return name
            except Exception:
                pass
        # Fallback: directory name
        return self.root_path.name

    # ------------------------------------------------------------------
    # File info
    # ------------------------------------------------------------------

    def _get_file_info(self, path: Path) -> FileInfo:
        language = LANGUAGE_MAP.get(path.suffix.lower(), "unknown")
        try:
            size = path.stat().st_size
            content = path.read_text(encoding="utf-8", errors="ignore")
            lines = len(content.splitlines())
        except Exception:
            size = 0
            lines = 0
        return FileInfo(
            path=str(path.relative_to(self.root_path)),
            language=language,
            size=size,
            lines=lines,
        )

    # ------------------------------------------------------------------
    # Manifest parsers
    # ------------------------------------------------------------------

    def _check_manifest(self, path: Path) -> Optional[ManifestInfo]:
        name = path.name.lower()
        if name == "requirements.txt":
            return ManifestInfo(type="pip", dependencies=self._parse_requirements(path))
        if name == "pyproject.toml":
            return ManifestInfo(type="pip", dependencies=self._parse_pyproject(path))
        if name == "package.json":
            return ManifestInfo(
                type="npm",
                dependencies=self._parse_package_json(path),
                metadata=self._get_package_metadata(path),
            )
        if name == "go.mod":
            return ManifestInfo(type="go", dependencies=self._parse_go_mod(path))
        if name == "cargo.toml":
            return ManifestInfo(type="cargo", dependencies=self._parse_cargo_toml(path))
        return None

    def _parse_requirements(self, path: Path) -> List[str]:
        deps = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-", "git+")):
                    continue
                pkg = line.split("==")[0].split(">=")[0].split("<=")[0]
                pkg = pkg.split("~=")[0].split("!=")[0].split("<")[0].split(">")[0]
                pkg = pkg.split("[")[0].strip()
                if pkg:
                    deps.append(pkg)
        except Exception:
            pass
        return deps

    def _parse_pyproject(self, path: Path) -> List[str]:
        """Parse pyproject.toml using tomllib (Python ≥ 3.11 stdlib)."""
        deps = []
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            raw = data.get("project", {}).get("dependencies", [])
            for dep in raw:
                name = dep.split(">=")[0].split("<=")[0].split("!=")[0]
                name = name.split("==")[0].split("~=")[0].split("<")[0].split(">")[0]
                name = name.split("[")[0].strip().strip("\"'")
                if name:
                    deps.append(name)
        except Exception:
            # Fallback regex for malformed or older TOML
            try:
                text = path.read_text(encoding="utf-8")
                for m in re.finditer(r'"([A-Za-z0-9_\-]+)[^"]*"', text):
                    name = m.group(1)
                    if name and not name.startswith(("python", ">=", "<", "!")):
                        deps.append(name)
            except Exception:
                pass
        return deps

    def _parse_package_json(self, path: Path) -> List[str]:
        deps = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                deps.extend(data.get(key, {}).keys())
        except Exception:
            pass
        return deps

    def _get_package_metadata(self, path: Path) -> Dict[str, str]:
        meta = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for k in ("name", "version", "description"):
                meta[k] = data.get(k, "")
        except Exception:
            pass
        return meta

    def _parse_go_mod(self, path: Path) -> List[str]:
        deps = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("require ") or (line and not line.startswith(("/", "module", "go "))):
                    parts = line.split()
                    if parts and "/" in parts[0]:
                        deps.append(parts[0])
        except Exception:
            pass
        return deps

    def _parse_cargo_toml(self, path: Path) -> List[str]:
        deps = []
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            deps.extend(data.get("dependencies", {}).keys())
            deps.extend(data.get("dev-dependencies", {}).keys())
        except Exception:
            pass
        return deps


def ingest_repository(root_path: str, max_files: int = 1000) -> Dict:
    """Convenience function to ingest a repository."""
    ingester = RepoIngester(root_path)
    return ingester.scan(max_files=max_files)
