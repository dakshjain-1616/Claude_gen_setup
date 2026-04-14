"""Gradio web interface for ClaudeGen."""

import os
import tempfile
from pathlib import Path
from typing import Generator


def _run_pipeline(
    repo_path: str,
    voice_file,
    token_budget: int,
    max_files: int,
    model: str,
) -> Generator[tuple, None, None]:
    """Run the full pipeline; yields (log, claude_md, graph_html) tuples."""
    log_lines: list = []

    def emit(msg: str) -> str:
        log_lines.append(msg)
        return "\n".join(log_lines)

    yield emit("Starting ClaudeGen…"), "", ""

    if not repo_path or not Path(repo_path).is_dir():
        yield emit(f"❌ Invalid repository path: {repo_path}"), "", ""
        return

    # Phase 1 — ingestion
    from claudegen.ingestion import RepoIngester
    yield emit("Phase 1: Scanning repository…"), "", ""
    ingester = RepoIngester(repo_path)
    scan_result = ingester.scan(max_files=int(max_files))
    frameworks_str = (", ".join(scan_result["frameworks"])) if scan_result.get("frameworks") else "none detected"
    yield emit(
        f"  ✓ {scan_result['file_count']} files | langs: {', '.join(scan_result['languages'])} | frameworks: {frameworks_str}"
    ), "", ""

    # Phase 2 — graph
    from claudegen.graph import DependencyGraph
    yield emit("Phase 2: Building dependency graph…"), "", ""
    dep_graph = DependencyGraph()
    file_tuples = [(str(Path(repo_path) / f.path), f.language) for f in ingester.files]
    dep_graph.build_graph(file_tuples, root_path=repo_path)
    cycles_abs = dep_graph.find_cycles()
    critical_abs = dep_graph.critical_files(top_n=10)
    root = Path(repo_path)

    def _rel(p: str) -> str:
        try:
            return str(Path(p).relative_to(root))
        except ValueError:
            return p

    critical = [(_rel(f), n) for f, n in critical_abs]
    cycles = [[_rel(node) for node in cycle] for cycle in cycles_abs]
    yield emit(f"  ✓ {len(dep_graph.graph.nodes())} nodes, {len(cycles)} cycles"), "", ""

    # Phase 3 — voice (optional)
    voice_text = None
    if voice_file is not None:
        yield emit("Phase 3: Transcribing voice notes…"), "", ""
        try:
            from claudegen.voice import VoiceTranscriber
            result = VoiceTranscriber().transcribe(voice_file)
            voice_text = result["text"]
            yield emit(f"  ✓ Transcribed ({len(voice_text)} chars)"), "", ""
        except Exception as exc:
            yield emit(f"  ⚠ Voice transcription failed: {exc}"), "", ""

    # Phase 4 — synthesis
    from claudegen.synthesis import ClaudeSynthesizer, ClaudeMdConfig
    yield emit("Phase 4: Generating CLAUDE.md…"), "", ""

    all_deps: list = []
    for m in ingester.manifests:
        all_deps.extend(m.dependencies)
    all_deps = list(dict.fromkeys(all_deps))

    config = ClaudeMdConfig(
        project_name=ingester.project_name(),
        description=f"Repository: {repo_path}",
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
    synthesizer = ClaudeSynthesizer(model=model, token_budget=int(token_budget))
    content = synthesizer.generate_claude_md(config)
    yield emit("  ✓ CLAUDE.md generated"), content, ""

    # Build graph HTML inline
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
            tmp_path = tmp.name
        dep_graph.export_html(tmp_path)
        graph_html = Path(tmp_path).read_text()
    except Exception:
        graph_html = ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    yield emit("✅ Done!"), content, graph_html


def create_ui():
    """Build and return the Gradio Blocks interface."""
    import gradio as gr

    with gr.Blocks(title="ClaudeGen", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# ClaudeGen\n"
            "**Auto-generate CLAUDE.md files with dependency graph analysis**\n\n"
            "Set `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` for LLM-enhanced output."
        )

        with gr.Row():
            # ── Left column: inputs ──────────────────────────────────
            with gr.Column(scale=1):
                repo_path_in = gr.Textbox(
                    label="Repository Path",
                    placeholder="/path/to/your/repo",
                )
                voice_file_in = gr.Audio(
                    label="Voice Notes (optional — WAV/MP3)",
                    type="filepath",
                    sources=["upload"],
                )
                token_budget_in = gr.Slider(
                    label="Token Budget",
                    minimum=1000,
                    maximum=8000,
                    value=4000,
                    step=500,
                )
                max_files_in = gr.Slider(
                    label="Max Files to Scan",
                    minimum=100,
                    maximum=5000,
                    value=1000,
                    step=100,
                )
                model_in = gr.Textbox(
                    label="Model (via OpenRouter)",
                    value="anthropic/claude-sonnet-4-6",
                )
                generate_btn = gr.Button("Generate CLAUDE.md", variant="primary")

            # ── Center column: log ───────────────────────────────────
            with gr.Column(scale=1):
                log_output = gr.Textbox(
                    label="Progress Log",
                    lines=20,
                    interactive=False,
                )

            # ── Right column: outputs ────────────────────────────────
            with gr.Column(scale=1):
                claude_md_out = gr.Textbox(
                    label="Generated CLAUDE.md",
                    lines=20,
                    interactive=False,
                    show_copy_button=True,
                )
                download_btn = gr.DownloadButton(label="⬇ Download CLAUDE.md")
                graph_html_out = gr.HTML(label="Dependency Graph")

        # Wire up generate button
        def on_generate(repo, voice, budget, mf, mdl):
            for log, md, gh in _run_pipeline(repo, voice, budget, mf, mdl):
                yield log, md, gh

        generate_btn.click(
            fn=on_generate,
            inputs=[repo_path_in, voice_file_in, token_budget_in, max_files_in, model_in],
            outputs=[log_output, claude_md_out, graph_html_out],
        )

        # Wire up download button — writes content to a temp file, returns path
        def save_for_download(content: str):
            if not content:
                return None
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", prefix="CLAUDE_", delete=False
            )
            tmp.write(content)
            tmp.close()
            return tmp.name

        download_btn.click(
            fn=save_for_download,
            inputs=[claude_md_out],
            outputs=[download_btn],
        )

    return demo


def launch(host: str = "127.0.0.1", port: int = 7860):
    """Launch the Gradio UI."""
    demo = create_ui()
    demo.launch(server_name=host, server_port=port)
