"""Click CLI entry point for ClaudeGen."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@click.group()
@click.version_option(package_name="claudegen")
def main():
    """ClaudeGen — auto-generate CLAUDE.md files for any repository."""


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", default=None, help="Output file path (default: CLAUDE.md inside the target repo).")
@click.option("--max-files", "-m", default=1000, help="Maximum source files to scan.")
@click.option(
    "--voice-notes", "-v",
    default=None,
    type=click.Path(exists=True),
    help="Path to an audio file (WAV/MP3) for voice transcription.",
)
@click.option("--model", default="anthropic/claude-sonnet-4-6", help="LLM model via OpenRouter.")
@click.option("--token-budget", default=4000, help="Max tokens for the generated CLAUDE.md.")
@click.option("--dry-run", is_flag=True, help="Print to stdout instead of writing files.")
def run(path, output, max_files, voice_notes, model, token_budget, dry_run):
    """Generate CLAUDE.md for a repository at PATH."""
    from claudegen.ingestion import RepoIngester
    from claudegen.graph import DependencyGraph
    from claudegen.synthesis import ClaudeSynthesizer, ClaudeMdConfig

    repo_path = Path(path).resolve()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:

        # ── Phase 1: Ingestion ────────────────────────────────────────
        task = progress.add_task("Phase 1: Scanning repository…", total=None)
        ingester = RepoIngester(str(repo_path))
        scan_result = ingester.scan(max_files=max_files)
        progress.update(
            task,
            description=(
                f"Phase 1: {scan_result['file_count']} files"
                + (f", {', '.join(scan_result['frameworks'])}" if scan_result.get('frameworks') else "")
            ),
        )
        progress.stop_task(task)

        # ── Phase 2: Dependency graph ─────────────────────────────────
        task = progress.add_task("Phase 2: Building dependency graph…", total=None)
        graph = DependencyGraph()
        file_tuples = [(str(repo_path / f.path), f.language) for f in ingester.files]
        graph.build_graph(file_tuples, root_path=str(repo_path))
        cycles_abs = graph.find_cycles()
        _critical_abs = graph.critical_files(top_n=10)

        def _rel(p: str) -> str:
            """Convert an absolute path to repo-relative; leave external names as-is."""
            try:
                return str(Path(p).relative_to(repo_path))
            except ValueError:
                return p

        # Make file paths relative to repo root for readable output
        critical = [(_rel(f), n) for f, n in _critical_abs]
        cycles = [[_rel(node) for node in cycle] for cycle in cycles_abs]
        progress.update(
            task,
            description=f"Phase 2: {len(graph.graph.nodes())} nodes, {len(cycles)} cycles",
        )
        progress.stop_task(task)

        # ── Phase 3: Voice (optional) ─────────────────────────────────
        voice_text: str | None = None
        if voice_notes:
            task = progress.add_task("Phase 3: Transcribing voice notes…", total=None)
            from claudegen.voice import VoiceTranscriber
            result = VoiceTranscriber().transcribe(voice_notes)
            voice_text = result["text"]
            progress.update(task, description="Phase 3: Voice transcription complete")
            progress.stop_task(task)

        # ── Phase 4: Synthesis ────────────────────────────────────────
        task = progress.add_task("Phase 4: Generating CLAUDE.md…", total=None)

        all_deps: list = []
        for m in ingester.manifests:
            all_deps.extend(m.dependencies)
        all_deps = list(dict.fromkeys(all_deps))

        config = ClaudeMdConfig(
            project_name=ingester.project_name(),
            description=f"Repository at {repo_path}",
            main_technologies=list(scan_result.get("languages", [])),
            key_files=[f for f, _ in critical],
            dependencies=all_deps,
            voice_notes=voice_text,
            circular_deps=cycles or None,
            critical_files=critical or None,
            frameworks=scan_result.get("frameworks") or None,
            entry_points=scan_result.get("entry_points") or None,
            readme_content=ingester.readme_content or None,
        )
        synthesizer = ClaudeSynthesizer(model=model, token_budget=token_budget)
        content = synthesizer.generate_claude_md(config)
        progress.update(task, description="Phase 4: CLAUDE.md generated")
        progress.stop_task(task)

    # ── Phase 5: Output ───────────────────────────────────────────────
    if dry_run:
        console.print("\n[bold]─── CLAUDE.md (dry run) ───[/bold]")
        console.print(content)
        return

    out_path = Path(output) if output else repo_path / "CLAUDE.md"
    out_path.write_text(content)
    console.print(f"\n[green]✓[/green] CLAUDE.md → {out_path}")

    dot_claude = repo_path / ".claude"
    dot_claude.mkdir(exist_ok=True)
    graph.export_json(str(dot_claude / "dependency-graph.json"))
    graph.export_html(str(dot_claude / "dependency-graph.html"))
    console.print(f"[green]✓[/green] Dependency graph → {dot_claude / 'dependency-graph.html'}")

    if voice_text:
        (dot_claude / "voice-notes.txt").write_text(voice_text)
        console.print(f"[green]✓[/green] Voice notes → {dot_claude / 'voice-notes.txt'}")


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--output-dir", "-d", default=".", help="Directory to write graph files.")
@click.option("--max-files", "-m", default=1000, help="Maximum source files to scan.")
def graph(path, output_dir, max_files):
    """Build and export the dependency graph for a repository at PATH."""
    from claudegen.ingestion import RepoIngester
    from claudegen.graph import DependencyGraph

    repo_path = Path(path).resolve()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning repository…", total=None)
        ingester = RepoIngester(str(repo_path))
        scan_result = ingester.scan(max_files=max_files)
        progress.update(task, description=f"Scanned {scan_result['file_count']} files")
        progress.stop_task(task)

        task = progress.add_task("Building dependency graph…", total=None)
        dep_graph = DependencyGraph()
        file_tuples = [(str(repo_path / f.path), f.language) for f in ingester.files]
        dep_graph.build_graph(file_tuples, root_path=str(repo_path))
        progress.stop_task(task)

    json_path = out_dir / "dependency-graph.json"
    html_path = out_dir / "dependency-graph.html"
    dep_graph.export_json(str(json_path))
    dep_graph.export_html(str(html_path))

    cycles = dep_graph.find_cycles()
    critical = dep_graph.critical_files(top_n=5)

    console.print(f"\n[green]✓[/green] JSON → {json_path}")
    console.print(f"[green]✓[/green] HTML → {html_path}")
    console.print(f"\n[bold]Nodes:[/bold] {len(dep_graph.graph.nodes())}")
    console.print(f"[bold]Edges:[/bold] {len(dep_graph.graph.edges())}")
    console.print(f"[bold]Cycles:[/bold] {len(cycles)}")
    if critical:
        console.print("\n[bold]Top files by in-degree:[/bold]")
        for f, n in critical:
            rel = str(Path(f).relative_to(repo_path)) if Path(f).is_absolute() else f
            console.print(f"  {rel}  [dim]({n} import{'s' if n != 1 else ''})[/dim]")


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--port", default=7860, help="Port to listen on.")
def ui(host, port):
    """Launch the Gradio web interface."""
    try:
        from claudegen.ui import launch
    except ImportError as exc:
        console.print(f"[red]Error loading UI:[/red] {exc}")
        console.print("Make sure gradio is installed: pip install gradio")
        sys.exit(1)
    console.print(f"[bold]Launching ClaudeGen UI at http://{host}:{port}[/bold]")
    launch(host=host, port=port)
