"""LLM synthesis module — assembles repo metadata into a CLAUDE.md file."""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class ClaudeMdConfig:
    """All inputs used to generate a CLAUDE.md file."""
    project_name: str
    description: str
    main_technologies: List[str]
    key_files: List[str]
    dependencies: List[str]
    # Optional enrichment
    voice_notes:      Optional[str]       = None
    circular_deps:    Optional[List]      = None
    critical_files:   Optional[List[Tuple[str, int]]] = None
    conventions:      Optional[str]       = None
    architecture_notes: Optional[str]     = None
    frameworks:       Optional[List[str]] = None
    entry_points:     Optional[List[str]] = None
    readme_content:   Optional[str]       = None


class ClaudeSynthesizer:
    """Generates CLAUDE.md content — LLM via OpenRouter if key is set, else template."""

    DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

    def __init__(self, model: str = DEFAULT_MODEL, token_budget: int = 4000):
        self.model_name = model
        self.token_budget = token_budget
        self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_claude_md(self, config: ClaudeMdConfig) -> str:
        """Generate CLAUDE.md.  Uses LLM when API key is available."""
        client = self._get_client()
        if client:
            try:
                return self._llm_generate(client, config)
            except Exception:
                pass
        return self._template_generate(config)

    def _format_list(self, items: List[str], bullet: str = "- ") -> str:
        """Format a list as a markdown bulleted list."""
        if not items:
            return "_None_"
        return "\n".join(f"{bullet}{item}" for item in items)

    # ------------------------------------------------------------------
    # Template generation (no LLM needed)
    # ------------------------------------------------------------------

    def _template_generate(self, config: ClaudeMdConfig) -> str:
        s = []

        # Title
        s.append(f"# {config.project_name}\n")

        # Overview — prefer first non-empty paragraph from README
        description = config.description
        if config.readme_content:
            para = _first_paragraph(config.readme_content)
            if para:
                description = para
        s.append(f"## Project Overview\n\n{description}\n")

        # Tech stack — frameworks + languages
        tech_items: List[str] = []
        if config.frameworks:
            tech_items.extend(config.frameworks)
        if config.main_technologies:
            for t in config.main_technologies:
                if t.lower() not in {f.lower() for f in tech_items}:
                    tech_items.append(t.capitalize())
        if tech_items:
            s.append(f"## Technology Stack\n\n{self._format_list(tech_items)}\n")

        # Entry points
        if config.entry_points:
            s.append(f"## Entry Points\n\n{self._format_list(config.entry_points)}\n")

        # Key files — critical (most-imported) internal files from graph
        if config.critical_files:
            ranked = [f for f, n in config.critical_files if n > 0]
            fallback = [f for f, _ in config.critical_files]
            display = ranked or fallback
            if display:
                lines = []
                for idx, (fp, n) in enumerate(config.critical_files[:10], 1):
                    suffix = f" — imported by {n} file{'s' if n != 1 else ''}" if n > 0 else ""
                    lines.append(f"{idx}. `{fp}`{suffix}")
                s.append("## Key Files (start here)\n\nFiles ranked by import frequency:\n\n" +
                         "\n".join(lines) + "\n")
        elif config.key_files:
            s.append(f"## Key Files\n\n{self._format_list(config.key_files)}\n")

        # Dependencies
        if config.dependencies:
            s.append(f"## Dependencies\n\n{self._format_list(config.dependencies[:20])}\n")

        # Architecture notes
        if config.architecture_notes:
            s.append(f"## Architecture Notes\n\n{config.architecture_notes}\n")

        # Conventions
        if config.conventions:
            s.append(f"## Conventions\n\n{config.conventions}\n")

        # Voice notes → team notes
        if config.voice_notes:
            s.append(f"## Team Notes (from voice)\n\n{config.voice_notes}\n")

        # Circular dependencies
        if config.circular_deps:
            cycles_text = "\n".join(
                f"- {' → '.join(str(n) for n in c)}" for c in config.circular_deps[:10]
            )
            s.append(f"## Circular Dependencies (Fix These)\n\n{cycles_text}\n")

        return "\n".join(s)

    # ------------------------------------------------------------------
    # LLM generation
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            return self._client
        except Exception:
            return None

    def _llm_generate(self, client, config: ClaudeMdConfig) -> str:
        system = (
            "You are writing a CLAUDE.md file for an AI coding agent. Be specific, dense, and "
            "practical. Every sentence must save the agent time or prevent a mistake. Do not "
            "repeat information across sections. Keep the total under 4000 tokens. Use the "
            "dependency graph data to annotate which files are most important and flag any "
            "circular dependencies the agent must be aware of."
        )
        context = self._build_context(config)
        resp = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ],
            max_tokens=self.token_budget,
        )
        return resp.choices[0].message.content

    def _build_context(self, config: ClaudeMdConfig) -> str:
        parts = [f"Generate a CLAUDE.md for project: **{config.project_name}**"]
        if config.readme_content:
            snippet = _first_paragraph(config.readme_content) or config.readme_content[:400]
            parts.append(f"README excerpt:\n{snippet}")
        parts.append(f"Description: {config.description}")
        if config.frameworks:
            parts.append("Frameworks: " + ", ".join(config.frameworks))
        if config.main_technologies:
            parts.append("Languages: " + ", ".join(config.main_technologies))
        if config.entry_points:
            parts.append("Entry points: " + ", ".join(config.entry_points))
        if config.dependencies:
            parts.append("Key dependencies: " + ", ".join(config.dependencies[:15]))
        if config.critical_files:
            cf_lines = [
                f"  {fp} (imported by {n} file{'s' if n != 1 else ''})"
                for fp, n in config.critical_files[:10]
                if n > 0
            ]
            if cf_lines:
                parts.append("Most-imported files:\n" + "\n".join(cf_lines))
        if config.circular_deps:
            cd = "\n".join("  " + " → ".join(str(n) for n in c) for c in config.circular_deps[:5])
            parts.append(f"Circular dependencies:\n{cd}")
        if config.voice_notes:
            parts.append(f"Team notes (voice): {config.voice_notes}")
        if config.conventions:
            parts.append(f"Conventions: {config.conventions}")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_paragraph(text: str) -> str:
    """Return the first non-heading, non-empty paragraph from markdown text."""
    lines = text.splitlines()
    para_lines: List[str] = []
    in_para = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if in_para:
                break
            continue
        if stripped:
            para_lines.append(stripped)
            in_para = True
        elif in_para:
            break
    return " ".join(para_lines)[:500]
