"""Dependency graph builder using tree-sitter AST parsing and NetworkX."""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

try:
    import tree_sitter_python as tspython
    import tree_sitter_javascript as tsjavascript
    import tree_sitter_typescript as tstypescript
    from tree_sitter import Language, Parser as TSParser
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False


def _make_parser(language_obj):
    from tree_sitter import Parser as TSParser
    return TSParser(language_obj)


class DependencyGraph:
    """Builds and analyzes a file-level dependency graph for a repository."""

    def __init__(self):
        self.graph = nx.DiGraph()
        self._entry_points: Set[str] = set()
        self._cycle_nodes: Set[str] = set()

    # ------------------------------------------------------------------
    # Import extraction — returns full dotted module names (e.g. "os", "claudegen.graph")
    # ------------------------------------------------------------------

    def extract_imports_python(self, file_path: str) -> List[str]:
        """Extract imported module names from a Python file.

        Returns full dotted module paths (e.g. 'pathlib', 'claudegen.graph').
        """
        imports: List[str] = []
        try:
            code = Path(file_path).read_bytes()
        except Exception:
            return imports

        if _TS_AVAILABLE:
            try:
                lang = Language(tspython.language())
                parser = _make_parser(lang)
                tree = parser.parse(code)
                self._walk_python_imports(tree.root_node, imports)
                return list(dict.fromkeys(imports))
            except Exception:
                pass

        # Regex fallback
        text = code.decode("utf-8", errors="ignore")
        for m in re.finditer(r"^import\s+([\w.]+)", text, re.MULTILINE):
            # Keep only top-level for bare imports: "import os.path" → "os"
            imports.append(m.group(1).split(".")[0])
        for m in re.finditer(r"^from\s+([\w.]+)\s+import", text, re.MULTILINE):
            # Keep full dotted path: "from claudegen.graph import X" → "claudegen.graph"
            imports.append(m.group(1))
        return list(dict.fromkeys(imports))

    def _walk_python_imports(self, node, imports: List[str]):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "aliased_import":
                    # "import numpy as np" → "numpy"
                    for subchild in child.children:
                        if subchild.type == "dotted_name":
                            name = subchild.text.decode("utf-8").split(".")[0].strip()
                            if name:
                                imports.append(name)
                            break
                elif child.type == "dotted_name":
                    # "import os" → "os"
                    name = child.text.decode("utf-8").split(".")[0].strip()
                    if name:
                        imports.append(name)
        elif node.type == "import_from_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    # "from claudegen.graph import X" → "claudegen.graph" (full path)
                    name = child.text.decode("utf-8").strip()
                    if name:
                        imports.append(name)
                    break  # only the module part, not the imported names
        for child in node.children:
            self._walk_python_imports(child, imports)

    def extract_imports_js(self, file_path: str) -> List[str]:
        """Extract imported module names from a JavaScript file."""
        return self._extract_js_ts_imports(file_path, "javascript")

    def extract_imports_ts(self, file_path: str) -> List[str]:
        """Extract imported module names from a TypeScript file."""
        return self._extract_js_ts_imports(file_path, "typescript")

    @staticmethod
    def _pkg_name(raw: str) -> str:
        """Canonical package name from an import specifier.

        @scope/name[/sub] → @scope/name  |  pkg/sub → pkg
        """
        if raw.startswith("@"):
            parts = raw.split("/")
            return "/".join(parts[:2]) if len(parts) >= 2 else raw
        return raw.split("/")[0]

    def _extract_js_ts_imports(self, file_path: str, lang_hint: str) -> List[str]:
        imports: List[str] = []
        try:
            code = Path(file_path).read_bytes()
        except Exception:
            return imports

        if _TS_AVAILABLE:
            try:
                if lang_hint == "typescript":
                    lang = Language(tstypescript.language_typescript())
                else:
                    lang = Language(tsjavascript.language())
                parser = _make_parser(lang)
                tree = parser.parse(code)
                self._walk_js_imports(tree.root_node, imports, file_path)
                return imports
            except Exception:
                pass

        # Regex fallback
        text = code.decode("utf-8", errors="ignore")
        for m in re.finditer(r"""import\s+(?:.*?\s+from\s+)?['"]([^'"]+)['"]""", text):
            raw = m.group(1)
            if raw.startswith("."):
                resolved = self._resolve_relative_js(raw, file_path)
                if resolved:
                    imports.append(resolved)
            else:
                imports.append(self._pkg_name(raw))
        for m in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]""", text):
            raw = m.group(1)
            if raw.startswith("."):
                resolved = self._resolve_relative_js(raw, file_path)
                if resolved:
                    imports.append(resolved)
            else:
                imports.append(self._pkg_name(raw))
        return list(dict.fromkeys(imports))

    def _walk_js_imports(self, node, imports: List[str], current_file: str):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "string":
                    raw = child.text.decode("utf-8").strip("'\"`")
                    if raw.startswith("."):
                        resolved = self._resolve_relative_js(raw, current_file)
                        if resolved:
                            imports.append(resolved)
                    elif raw:
                        imports.append(self._pkg_name(raw))
        elif node.type in ("call_expression", "new_expression"):
            children = node.children
            if children and children[0].text in (b"require",):
                for child in children[1:]:
                    if child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "string":
                                raw = arg.text.decode("utf-8").strip("'\"`")
                                if raw.startswith("."):
                                    resolved = self._resolve_relative_js(raw, current_file)
                                    if resolved:
                                        imports.append(resolved)
                                elif raw:
                                    imports.append(self._pkg_name(raw))
        for child in node.children:
            self._walk_js_imports(child, imports, current_file)

    @staticmethod
    def _resolve_relative_js(specifier: str, current_file: str) -> Optional[str]:
        """Resolve a relative JS/TS import specifier to an absolute file path."""
        current_dir = Path(current_file).parent
        target = (current_dir / specifier).resolve()
        for ext in [".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"]:
            candidate = target.with_suffix(ext)
            if candidate.exists():
                return str(candidate)
        for ext in [".js", ".ts"]:
            candidate = target / f"index{ext}"
            if candidate.exists():
                return str(candidate)
        # Return the resolved path even if it doesn't exist on disk
        # (the file might be generated/compiled)
        return str(target)

    # ------------------------------------------------------------------
    # Internal module map (Python)
    # ------------------------------------------------------------------

    def _build_py_module_map(
        self, files: List[Tuple[str, str]], root: Path
    ) -> Dict[str, str]:
        """Return {dotted_module_name: abs_file_path} for all Python files under root."""
        module_map: Dict[str, str] = {}
        for file_path, language in files:
            if language != "python":
                continue
            p = Path(file_path)
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            parts = list(rel.with_suffix("").parts)
            # Full dotted name: claudegen/graph.py → "claudegen.graph"
            full_name = ".".join(parts)
            module_map[full_name] = file_path
            # Package init: claudegen/__init__.py → "claudegen"
            if parts[-1] == "__init__" and len(parts) > 1:
                module_map[".".join(parts[:-1])] = file_path
            # Bare stem as last-resort: "graph" → claudegen/graph.py
            if parts[-1] != "__init__":
                module_map.setdefault(parts[-1], file_path)
        return module_map

    def _resolve_py_import(
        self, imp: str, module_map: Dict[str, str]
    ) -> str:
        """Resolve a Python import string to an internal file path if possible."""
        # Exact match: "claudegen.graph" → file
        if imp in module_map:
            return module_map[imp]
        # Try progressively shorter prefixes: "a.b.c" → try "a.b", then "a"
        parts = imp.split(".")
        for n in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:n])
            if candidate in module_map:
                return module_map[candidate]
        return imp  # stays as external node

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_graph(self, files: List[Tuple[str, str]], root_path: str = None):
        """Build the dependency graph.

        Args:
            files: List of (absolute_file_path, language) tuples.
            root_path: Repository root — used to resolve internal imports.
                       When provided, imports that resolve to project files create
                       edges between file nodes rather than to external module names.
        """
        root = Path(root_path) if root_path else None

        # Build Python module map for internal resolution
        py_module_map: Dict[str, str] = {}
        if root:
            py_module_map = self._build_py_module_map(files, root)

        # Ensure every source file is a node (even with no imports)
        for file_path, language in files:
            if not self.graph.has_node(file_path):
                self.graph.add_node(
                    file_path, language=language, in_cycle=False, is_entry=False
                )

        # Extract imports and add edges
        for file_path, language in files:
            if language == "python":
                raw_imports = self.extract_imports_python(file_path)
            elif language == "typescript":
                raw_imports = self.extract_imports_ts(file_path)
            elif language in ("javascript",):
                raw_imports = self.extract_imports_js(file_path)
            else:
                raw_imports = []

            for imp in raw_imports:
                if language == "python" and py_module_map:
                    target = self._resolve_py_import(imp, py_module_map)
                else:
                    target = imp

                if not self.graph.has_node(target):
                    # External package or unresolved path
                    is_internal = target in {fp for fp, _ in files}
                    self.graph.add_node(
                        target,
                        language="external" if not is_internal else language,
                        in_cycle=False,
                        is_entry=False,
                    )
                self.graph.add_edge(file_path, target)

        # Mark cycle nodes
        for cycle in self.find_cycles():
            for node in cycle:
                self._cycle_nodes.add(node)
                if self.graph.has_node(node):
                    self.graph.nodes[node]["in_cycle"] = True

    def find_cycles(self) -> List[List[str]]:
        """Return all simple cycles in the dependency graph."""
        try:
            return list(nx.simple_cycles(self.graph))
        except Exception:
            return []

    def critical_files(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """Return the top_n *internal* files ranked by in-degree.

        Only nodes whose ID looks like a file path (contains path separators or
        a code file extension) are included — external package names are excluded.
        """
        CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs")
        by_indegree = [
            (node, deg)
            for node, deg in self.graph.in_degree()
            if (
                # Absolute path
                node.startswith("/") or node.startswith("\\") or
                # Ends with a code extension
                node.endswith(CODE_EXTS) or
                # Relative path with separator — but NOT scoped npm packages (@scope/name)
                # and NOT URL-like strings
                ("/" in node and not node.startswith("@") and not node.startswith("http"))
            )
        ]
        by_indegree.sort(key=lambda x: x[1], reverse=True)
        return by_indegree[:top_n]

    def get_top_level_modules(self) -> List[str]:
        """Return all node names in the graph."""
        return list(self.graph.nodes())

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_json(self, output_path: str):
        """Write the graph as JSON with node metadata."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "indegree": self.graph.in_degree(node_id),
                "outdegree": self.graph.out_degree(node_id),
                "is_entry": data.get("is_entry", False),
                "in_cycle": data.get("in_cycle", False),
                "language": data.get("language", "unknown"),
            })
        edges = [{"source": s, "target": t} for s, t in self.graph.edges()]
        Path(output_path).write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2))

    def export_html(self, output_path: str):
        """Write a self-contained D3 v7 force-directed graph HTML file."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "indegree": self.graph.in_degree(node_id),
                "in_cycle": data.get("in_cycle", False),
                "is_entry": data.get("is_entry", False),
            })
        edges = [{"source": s, "target": t} for s, t in self.graph.edges()]

        nodes_json = json.dumps(nodes)
        edges_json = json.dumps(edges)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Dependency Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  body {{ margin: 0; background: #1a1a2e; color: #eee; font-family: sans-serif; }}
  #info {{ position: fixed; top: 10px; left: 10px; background: rgba(0,0,0,.75);
           padding: 10px 14px; border-radius: 8px; max-width: 320px; font-size: 13px;
           line-height: 1.5; }}
  .link {{ stroke: #444; stroke-opacity: 0.5; }}
  .node circle {{ cursor: pointer; stroke-width: 1.5px; }}
  .node text {{ font-size: 10px; fill: #ccc; pointer-events: none; }}
  .legend {{ position: fixed; bottom: 14px; left: 14px; font-size: 12px; }}
  .legend span {{ display: inline-block; width: 12px; height: 12px;
                  border-radius: 50%; margin-right: 5px; vertical-align: middle; }}
</style>
</head>
<body>
<div id="info">Hover a node to see details</div>
<div class="legend">
  <span style="background:#e74c3c"></span>Circular dep &nbsp;
  <span style="background:#9b59b6"></span>Entry point &nbsp;
  <span style="background:#3498db"></span>Internal file &nbsp;
  <span style="background:#7f8c8d"></span>External package
</div>
<svg width="100%" height="100vh"></svg>
<script>
const nodesData = {nodes_json};
const linksData = {edges_json};

const svg = d3.select("svg");
const width = window.innerWidth, height = window.innerHeight;
const g = svg.append("g");

svg.call(d3.zoom().scaleExtent([0.1, 10]).on("zoom", e => g.attr("transform", e.transform)));

const sim = d3.forceSimulation(nodesData)
  .force("link", d3.forceLink(linksData).id(d => d.id).distance(90))
  .force("charge", d3.forceManyBody().strength(-140))
  .force("center", d3.forceCenter(width / 2, height / 2));

const link = g.selectAll(".link")
  .data(linksData).enter().append("line").attr("class", "link");

const nodeG = g.selectAll(".node")
  .data(nodesData).enter().append("g").attr("class", "node")
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag",  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end",   (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}))
  .on("mouseover", (e, d) => {{
    const label = d.id.includes('/') || d.id.includes('\\\\')
      ? d.id.split('/').pop().split('\\\\').pop()
      : d.id;
    document.getElementById("info").innerHTML =
      `<b>${{d.id}}</b><br>In-degree: <b>${{d.indegree}}</b>` +
      (d.in_cycle ? '<br><span style="color:#e74c3c">⚠ In circular dependency</span>' : '') +
      (d.is_entry ? '<br><span style="color:#9b59b6">★ Entry point</span>' : '');
  }});

const color = d => d.in_cycle ? "#e74c3c" : d.is_entry ? "#9b59b6"
  : (d.id.includes('/') || d.id.endsWith('.py') || d.id.endsWith('.js') || d.id.endsWith('.ts'))
  ? "#3498db" : "#7f8c8d";

nodeG.append("circle")
  .attr("r", d => Math.max(4, Math.sqrt((d.indegree || 0) + 1) * 5))
  .attr("fill", color)
  .attr("stroke", "#fff");

nodeG.append("text").attr("dx", 8).attr("dy", 4)
  .text(d => {{
    const s = d.id.split('/').pop().split('\\\\').pop();
    return s.length > 25 ? s.slice(0, 22) + '...' : s;
  }});

sim.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  nodeG.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});
</script>
</body>
</html>"""
        Path(output_path).write_text(html)
