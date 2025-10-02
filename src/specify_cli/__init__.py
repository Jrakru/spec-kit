#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer",
#     "rich",
#     "platformdirs",
#     "readchar",
#     "httpx",
# ]
# ///
"""
Specify CLI - Setup tool for Specify projects

Usage:
    uvx specify-cli.py init <project-name>
    uvx specify-cli.py init --here

Or install globally:
    uv tool install --from specify-cli.py specify-cli
    specify init <project-name>
    specify init --here
"""

import os
import subprocess
import sys
import zipfile
import tempfile
import shutil
import shlex
import json
import re
from pathlib import Path
from typing import Optional, Sequence, Tuple, List

import typer
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text
from rich.live import Live
from rich.align import Align
from rich.table import Table
from .paths import get_specs_root, get_specify_root, specify_scripts_dir, specify_templates_dir
from rich.tree import Tree
from typer.core import TyperGroup

# For cross-platform keyboard input
import readchar
import ssl
import truststore

ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
client = httpx.Client(verify=ssl_context)

def _github_token(cli_token: str | None = None) -> str | None:
    """Return sanitized GitHub token (cli arg takes precedence) or None."""
    return ((cli_token or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()) or None

def _github_auth_headers(cli_token: str | None = None) -> dict:
    """Return Authorization header dict only when a non-empty token exists."""
    token = _github_token(cli_token)
    return {"Authorization": f"Bearer {token}"} if token else {}

# Constants
AI_CHOICES = {
    "copilot": "GitHub Copilot",
    "claude": "Claude Code",
    "gemini": "Gemini CLI",
    "cursor": "Cursor",
    "qwen": "Qwen Code",
    "opencode": "opencode",
    "codex": "Codex CLI",
    "windsurf": "Windsurf",
    "kilocode": "Kilo Code",
    "auggie": "Auggie CLI",
    "roo": "Roo Code",
}

AGENT_DIRECTORY_MAP = {
    "claude": ".claude/",
    "gemini": ".gemini/",
    "cursor": ".cursor/",
    "qwen": ".qwen/",
    "opencode": ".opencode/",
    "codex": ".codex/",
    "windsurf": ".windsurf/",
    "kilocode": ".kilocode/",
    "auggie": ".augment/",
    "copilot": ".github/",
    "roo": ".roo/",
}

AGENT_ROOT_NAMES = {key: Path(path).parts[0] for key, path in AGENT_DIRECTORY_MAP.items()}
# Add script type choices
SCRIPT_TYPE_CHOICES = {"sh": "POSIX Shell (bash/zsh)", "ps": "PowerShell"}

# Keep a module version (mirrors pyproject.toml). Update alongside pyproject version bump.
__version__ = "0.0.57"

# Claude CLI local installation path after migrate-installer
CLAUDE_LOCAL_PATH = Path.home() / ".claude" / "local" / "claude"

# ASCII Art Banner
BANNER = """
███████╗██████╗ ███████╗ ██████╗██╗███████╗██╗   ██╗
██╔════╝██╔══██╗██╔════╝██╔════╝██║██╔════╝╚██╗ ██╔╝
███████╗██████╔╝█████╗  ██║     ██║█████╗   ╚████╔╝ 
╚════██║██╔═══╝ ██╔══╝  ██║     ██║██╔══╝    ╚██╔╝  
███████║██║     ███████╗╚██████╗██║██║        ██║   
╚══════╝╚═╝     ╚══════╝ ╚═════╝╚═╝╚═╝        ╚═╝   
"""

TAGLINE = "GitHub Spec Kit - Spec-Driven Development Toolkit"
class StepTracker:
    """Track and render hierarchical steps without emojis, similar to Claude Code tree output.
    Supports live auto-refresh via an attached refresh callback.
    """
    def __init__(self, title: str):
        self.title = title
        self.steps = []  # list of dicts: {key, label, status, detail}
        self.status_order = {"pending": 0, "running": 1, "done": 2, "error": 3, "skipped": 4}
        self._refresh_cb = None  # callable to trigger UI refresh

    def attach_refresh(self, cb):
        self._refresh_cb = cb

    def add(self, key: str, label: str):
        if key not in [s["key"] for s in self.steps]:
            self.steps.append({"key": key, "label": label, "status": "pending", "detail": ""})
            self._maybe_refresh()

    def start(self, key: str, detail: str = ""):
        self._update(key, status="running", detail=detail)

    def complete(self, key: str, detail: str = ""):
        self._update(key, status="done", detail=detail)

    def error(self, key: str, detail: str = ""):
        self._update(key, status="error", detail=detail)

    def skip(self, key: str, detail: str = ""):
        self._update(key, status="skipped", detail=detail)

    def _update(self, key: str, status: str, detail: str):
        for s in self.steps:
            if s["key"] == key:
                s["status"] = status
                if detail:
                    s["detail"] = detail
                self._maybe_refresh()
                return
        # If not present, add it
        self.steps.append({"key": key, "label": key, "status": status, "detail": detail})
        self._maybe_refresh()

    def _maybe_refresh(self):
        if self._refresh_cb:
            try:
                self._refresh_cb()
            except Exception:
                pass

    def render(self):
        tree = Tree(f"[cyan]{self.title}[/cyan]", guide_style="grey50")
        for step in self.steps:
            label = step["label"]
            detail_text = step["detail"].strip() if step["detail"] else ""

            # Circles (unchanged styling)
            status = step["status"]
            if status == "done":
                symbol = "[green]●[/green]"
            elif status == "pending":
                symbol = "[green dim]○[/green dim]"
            elif status == "running":
                symbol = "[cyan]○[/cyan]"
            elif status == "error":
                symbol = "[red]●[/red]"
            elif status == "skipped":
                symbol = "[yellow]○[/yellow]"
            else:
                symbol = " "

            if status == "pending":
                # Entire line light gray (pending)
                if detail_text:
                    line = f"{symbol} [bright_black]{label} ({detail_text})[/bright_black]"
                else:
                    line = f"{symbol} [bright_black]{label}[/bright_black]"
            else:
                # Label white, detail (if any) light gray in parentheses
                if detail_text:
                    line = f"{symbol} [white]{label}[/white] [bright_black]({detail_text})[/bright_black]"
                else:
                    line = f"{symbol} [white]{label}[/white]"

            tree.add(line)
        return tree



MINI_BANNER = """
╔═╗╔═╗╔═╗╔═╗╦╔═╗╦ ╦
╚═╗╠═╝║╣ ║  ║╠╣ ╚╦╝
╚═╝╩  ╚═╝╚═╝╩╚   ╩ 
"""

def get_key():
    """Get a single keypress in a cross-platform way using readchar."""
    key = readchar.readkey()
    
    # Arrow keys
    if key == readchar.key.UP:
        return 'up'
    if key == readchar.key.DOWN:
        return 'down'
    
    # Enter/Return
    if key == readchar.key.ENTER:
        return 'enter'
    
    # Escape
    if key == readchar.key.ESC:
        return 'escape'
        
    # Ctrl+C
    if key == readchar.key.CTRL_C:
        raise KeyboardInterrupt

    return key



def select_with_arrows(options: dict, prompt_text: str = "Select an option", default_key: str = None) -> str:
    """
    Interactive selection using arrow keys with Rich Live display.
    
    Args:
        options: Dict with keys as option keys and values as descriptions
        prompt_text: Text to show above the options
        default_key: Default option key to start with
        
    Returns:
        Selected option key
    """
    option_keys = list(options.keys())
    if default_key and default_key in option_keys:
        selected_index = option_keys.index(default_key)
    else:
        selected_index = 0
    
    selected_key = None

    def create_selection_panel():
        """Create the selection panel with current selection highlighted."""
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan", justify="left", width=3)
        table.add_column(style="white", justify="left")
        
        for i, key in enumerate(option_keys):
            if i == selected_index:
                table.add_row("▶", f"[cyan]{key}[/cyan] [dim]({options[key]})[/dim]")
            else:
                table.add_row(" ", f"[cyan]{key}[/cyan] [dim]({options[key]})[/dim]")
        
        table.add_row("", "")
        table.add_row("", "[dim]Use ↑/↓ to navigate, Enter to select, Esc to cancel[/dim]")
        
        return Panel(
            table,
            title=f"[bold]{prompt_text}[/bold]",
            border_style="cyan",
            padding=(1, 2)
        )
    
    console.print()

    def run_selection_loop():
        nonlocal selected_key, selected_index
        with Live(create_selection_panel(), console=console, transient=True, auto_refresh=False) as live:
            while True:
                try:
                    key = get_key()
                    if key == 'up':
                        selected_index = (selected_index - 1) % len(option_keys)
                    elif key == 'down':
                        selected_index = (selected_index + 1) % len(option_keys)
                    elif key == 'enter':
                        selected_key = option_keys[selected_index]
                        break
                    elif key == 'escape':
                        console.print("\n[yellow]Selection cancelled[/yellow]")
                        raise typer.Exit(1)
                    
                    live.update(create_selection_panel(), refresh=True)

                except KeyboardInterrupt:
                    console.print("\n[yellow]Selection cancelled[/yellow]")
                    raise typer.Exit(1)

    run_selection_loop()

    if selected_key is None:
        console.print("\n[red]Selection failed.[/red]")
        raise typer.Exit(1)

    # Suppress explicit selection print; tracker / later logic will report consolidated status
    return selected_key



def _tokenize_ai_value(raw: str) -> List[str]:
    """Split a raw --ai token into normalized agent keys."""
    if raw is None:
        return []
    token = raw.strip()
    if not token:
        return []
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1]
    parts = [segment.strip().strip('[]"\'"') for segment in re.split(r"[\s,]+", token) if segment.strip()]
    return [part.lower() for part in parts if part]


def parse_ai_option_values(raw_values: Sequence[str] | None) -> List[str]:
    """Return ordered, deduplicated agent keys supplied via --ai."""
    if not raw_values:
        return []
    ordered: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for token in _tokenize_ai_value(raw):
            if token not in seen:
                ordered.append(token)
                seen.add(token)
    return ordered


def human_join(items: Sequence[str]) -> str:
    """Join values with commas and an 'and' before the final item."""
    filtered = [item for item in items if item]
    if not filtered:
        return ""
    if len(filtered) == 1:
        return filtered[0]
    return ", ".join(filtered[:-1]) + f", and {filtered[-1]}"


def find_agent_template_variant(base_dir: Path, agent: str, script_type: str) -> Path | None:
    """Locate a prebuilt agent template under base_dir for the given script type."""
    # Prefer directories first so we avoid repeated extraction work when available.
    dir_patterns = [
        f"sdd-{agent}-package-{script_type}",
        f"sdd-{agent}-package-{script_type}-*",
    ]
    for pattern in dir_patterns:
        candidates = sorted(base_dir.glob(pattern))
        for candidate in reversed(candidates):
            if candidate.is_dir():
                return candidate

    zip_patterns = [
        f"spec-kit-template-{agent}-{script_type}.zip",
        f"spec-kit-template-{agent}-{script_type}-*.zip",
    ]
    for pattern in zip_patterns:
        candidates = sorted(base_dir.glob(pattern))
        for candidate in reversed(candidates):
            if candidate.is_file():
                return candidate
    return None


console = Console()


class BannerGroup(TyperGroup):
    """Custom group that shows banner before help."""
    
    def format_help(self, ctx, formatter):
        # Show banner before help
        show_banner()
        super().format_help(ctx, formatter)


app = typer.Typer(
    name="specify",
    help="Setup tool for Specify spec-driven development projects",
    add_completion=False,
    invoke_without_command=True,
    cls=BannerGroup,
)


@app.command("version")
def version_command():
    """Print the Specify CLI version."""
    # Prefer importlib.metadata to ensure we reflect installed distribution when available.
    try:
        import importlib.metadata as md  # type: ignore
        dist_version = md.version("specify-cli")
        console.print(dist_version)
    except Exception:
        # Fallback to module constant
        console.print(__version__)
    raise typer.Exit(0)


def show_banner():
    """Display the ASCII art banner."""
    # Create gradient effect with different colors
    banner_lines = BANNER.strip().split('\n')
    colors = ["bright_blue", "blue", "cyan", "bright_cyan", "white", "bright_white"]
    
    styled_banner = Text()
    for i, line in enumerate(banner_lines):
        color = colors[i % len(colors)]
        styled_banner.append(line + "\n", style=color)
    
    console.print(Align.center(styled_banner))
    console.print(Align.center(Text(TAGLINE, style="italic bright_yellow")))
    console.print()


@app.callback()
def callback(ctx: typer.Context):
    """Show banner when no subcommand is provided."""
    # Show banner only when no subcommand and no help flag
    # (help is handled by BannerGroup)
    if ctx.invoked_subcommand is None and "--help" not in sys.argv and "-h" not in sys.argv:
        show_banner()
        console.print(Align.center("[dim]Run 'specify --help' for usage information[/dim]"))
        console.print()


def run_command(cmd: list[str], check_return: bool = True, capture: bool = False, shell: bool = False) -> Optional[str]:
    """Run a shell command and optionally capture output."""
    try:
        if capture:
            result = subprocess.run(cmd, check=check_return, capture_output=True, text=True, shell=shell)
            return result.stdout.strip()
        else:
            subprocess.run(cmd, check=check_return, shell=shell)
            return None
    except subprocess.CalledProcessError as e:
        if check_return:
            console.print(f"[red]Error running command:[/red] {' '.join(cmd)}")
            console.print(f"[red]Exit code:[/red] {e.returncode}")
            if hasattr(e, 'stderr') and e.stderr:
                console.print(f"[red]Error output:[/red] {e.stderr}")
            raise
        return None


def check_tool_for_tracker(tool: str, tracker: StepTracker) -> bool:
    """Check if a tool is installed and update tracker."""
    if shutil.which(tool):
        tracker.complete(tool, "available")
        return True
    else:
        tracker.error(tool, "not found")
        return False


def check_tool(tool: str, install_hint: str) -> bool:
    """Check if a tool is installed."""
    
    # Special handling for Claude CLI after `claude migrate-installer`
    # See: https://github.com/github/spec-kit/issues/123
    # The migrate-installer command REMOVES the original executable from PATH
    # and creates an alias at ~/.claude/local/claude instead
    # This path should be prioritized over other claude executables in PATH
    if tool == "claude":
        if CLAUDE_LOCAL_PATH.exists() and CLAUDE_LOCAL_PATH.is_file():
            return True
    
    if shutil.which(tool):
        return True
    else:
        return False


def is_git_repo(path: Path = None) -> bool:
    """Check if the specified path is inside a git repository."""
    if path is None:
        path = Path.cwd()
    
    if not path.is_dir():
        return False

    try:
        # Use git command to check if inside a work tree
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            cwd=path,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def init_git_repo(project_path: Path, quiet: bool = False) -> bool:
    """Initialize a git repository in the specified path.
    quiet: if True suppress console output (tracker handles status)
    """
    try:
        original_cwd = Path.cwd()
        os.chdir(project_path)
        if not quiet:
            console.print("[cyan]Initializing git repository...[/cyan]")
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit from Specify template"], check=True, capture_output=True)
        if not quiet:
            console.print("[green]✓[/green] Git repository initialized")
        return True
        
    except subprocess.CalledProcessError as e:
        if not quiet:
            console.print(f"[red]Error initializing git repository:[/red] {e}")
        return False
    finally:
        os.chdir(original_cwd)


def download_template_from_github(
    ai_assistant: str,
    download_dir: Path,
    *,
    script_type: str = "sh",
    verbose: bool = True,
    show_progress: bool = True,
    client: httpx.Client = None,
    debug: bool = False,
    github_token: str = None,
    repo_owner: str = "github",
    repo_name: str = "spec-kit",
) -> Tuple[Path, dict]:
    if client is None:
        client = httpx.Client(verify=ssl_context)
    
    if verbose:
        console.print("[cyan]Fetching latest release information...[/cyan]")
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
    
    try:
        response = client.get(
            api_url,
            timeout=30,
            follow_redirects=True,
            headers=_github_auth_headers(github_token),
        )
        status = response.status_code
        if status != 200:
            msg = f"GitHub API returned {status} for {api_url}"
            if debug:
                msg += f"\nResponse headers: {response.headers}\nBody (truncated 500): {response.text[:500]}"
            raise RuntimeError(msg)
        try:
            release_data = response.json()
        except ValueError as je:
            raise RuntimeError(f"Failed to parse release JSON: {je}\nRaw (truncated 400): {response.text[:400]}")
    except Exception as e:
        console.print(f"[red]Error fetching release information[/red]")
        console.print(Panel(str(e), title="Fetch Error", border_style="red"))
        raise typer.Exit(1)
    
    # Find the template asset for the specified AI assistant
    assets = release_data.get("assets", [])
    pattern = f"spec-kit-template-{ai_assistant}-{script_type}"
    matching_assets = [
        asset for asset in assets
        if pattern in asset["name"] and asset["name"].endswith(".zip")
    ]

    asset = matching_assets[0] if matching_assets else None

    if asset is None:
        console.print(f"[red]No matching release asset found[/red] for [bold]{ai_assistant}[/bold] (expected pattern: [bold]{pattern}[/bold])")
        asset_names = [a.get('name', '?') for a in assets]
        console.print(Panel("\n".join(asset_names) or "(no assets)", title="Available Assets", border_style="yellow"))
        raise typer.Exit(1)

    download_url = asset["browser_download_url"]
    filename = asset["name"]
    file_size = asset["size"]
    
    if verbose:
        console.print(f"[cyan]Found template:[/cyan] {filename}")
        console.print(f"[cyan]Size:[/cyan] {file_size:,} bytes")
        console.print(f"[cyan]Release:[/cyan] {release_data['tag_name']}")

    zip_path = download_dir / filename
    if verbose:
        console.print(f"[cyan]Downloading template...[/cyan]")
    
    try:
        with client.stream(
            "GET",
            download_url,
            timeout=60,
            follow_redirects=True,
            headers=_github_auth_headers(github_token),
        ) as response:
            if response.status_code != 200:
                body_sample = response.text[:400]
                raise RuntimeError(f"Download failed with {response.status_code}\nHeaders: {response.headers}\nBody (truncated): {body_sample}")
            total_size = int(response.headers.get('content-length', 0))
            with open(zip_path, 'wb') as f:
                if total_size == 0:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                else:
                    if show_progress:
                        with Progress(
                            SpinnerColumn(),
                            TextColumn("[progress.description]{task.description}"),
                            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                            console=console,
                        ) as progress:
                            task = progress.add_task("Downloading...", total=total_size)
                            downloaded = 0
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress.update(task, completed=downloaded)
                    else:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            f.write(chunk)
    except Exception as e:
        console.print(f"[red]Error downloading template[/red]")
        detail = str(e)
        if zip_path.exists():
            zip_path.unlink()
        console.print(Panel(detail, title="Download Error", border_style="red"))
        raise typer.Exit(1)
    if verbose:
        console.print(f"Downloaded: {filename}")
    metadata = {
        "filename": filename,
        "size": file_size,
        "release": release_data["tag_name"],
        "asset_url": download_url
    }
    return zip_path, metadata


def download_and_extract_template(
    project_path: Path,
    ai_assistant: str,
    script_type: str,
    is_current_dir: bool = False,
    *,
    verbose: bool = True,
    tracker: StepTracker | None = None,
    client: httpx.Client = None,
    debug: bool = False,
    github_token: str = None,
    template_repo: Tuple[str, str] | None = None,
    template_path: Path | None = None,
    tracker_agent_label: str | None = None,
    top_level_filter: Sequence[str] | None = None,
    preserve_existing_specs: bool = False,
) -> Path:
    """Provision project scaffolding from a release archive or local template."""
    current_dir = Path.cwd()
    repo_owner, repo_name = template_repo or ("github", "spec-kit")

    local_template_dir: Path | None = None
    zip_path: Path | None = None
    temp_dir_ctx: tempfile.TemporaryDirectory | None = None
    meta: dict = {}
    cleanup_zip = False
    using_local_template = template_path is not None
    filtered_top_level: set[str] | None = None
    if top_level_filter:
        filtered_top_level = set()
        for value in top_level_filter:
            if not value:
                continue
            parts = Path(value).parts
            filtered_top_level.add(parts[0] if parts else value)
        if not filtered_top_level:
            filtered_top_level = None

    def _tag(detail: str) -> str:
        return f"{tracker_agent_label} - {detail}" if tracker_agent_label else detail

    if template_path is not None:
        template_source = Path(template_path).expanduser().resolve()
        if not template_source.exists():
            message = f"Template path not found: {template_source}"
            if tracker:
                tracker.error("fetch", message)
            else:
                console.print(f"[red]{message}[/red]")
            raise typer.Exit(1)

        if template_source.is_dir():
            has_direct_assets = (template_source / ".specs").exists() or (template_source / ".specify").exists()
            if not has_direct_assets:
                variant = find_agent_template_variant(template_source, ai_assistant, script_type)
                if variant is None:
                    message = (
                        f"No template found for agent '{ai_assistant}' and script '{script_type}' in {template_source}"
                    )
                    if tracker:
                        tracker.error("fetch", _tag(message))
                    else:
                        console.print(f"[red]{message}[/red]")
                    raise typer.Exit(1)
                template_source = variant

        if template_source.is_dir():
            local_template_dir = template_source
            if tracker:
                tracker.skip("fetch", _tag("Local template directory"))
                tracker.skip("download", _tag(template_source.name))
            elif verbose:
                console.print(f"[cyan]Using local template directory:[/cyan] {template_source}")
        else:
            zip_path = template_source
            meta = {
                "filename": zip_path.name,
                "size": zip_path.stat().st_size,
                "release": "local",
            }
            if tracker:
                tracker.skip("fetch", _tag("Local template archive"))
                tracker.complete("download", _tag(zip_path.name))
            elif verbose:
                console.print(f"[cyan]Using local template archive:[/cyan] {zip_path}")
    else:
        if tracker:
            tracker.start("fetch", _tag("contacting GitHub API"))
        try:
            zip_path, meta = download_template_from_github(
                ai_assistant,
                current_dir,
                script_type=script_type,
                verbose=verbose and tracker is None,
                show_progress=(tracker is None),
                client=client,
                debug=debug,
                github_token=github_token,
                repo_owner=repo_owner,
                repo_name=repo_name,
            )
            cleanup_zip = True
            if tracker:
                tracker.complete("fetch", _tag(f"release {meta['release']} ({meta['size']:,} bytes)"))
                tracker.complete("download", _tag(meta['filename']))
        except Exception as e:
            if tracker:
                tracker.error("fetch", _tag(str(e)))
            else:
                if verbose:
                    console.print(f"[red]Error downloading template:[/red] {e}")
            raise

    if tracker:
        tracker.add("extract", "Extract template")
        tracker.start("extract", _tag("starting"))
    elif verbose:
        console.print("Extracting template...")

    def _copytree_preserve(src: Path, dest: Path) -> None:
        """Copy directory contents but skip files that already exist at destination."""
        if not dest.exists():
            shutil.copytree(src, dest)
            return
        dest.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            target = dest / child.name
            if child.is_dir():
                _copytree_preserve(child, target)
            else:
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)

    def _merge_into_project(payload_root: Path) -> None:
        resolved_project_path = project_path.resolve()
        for item in payload_root.iterdir():
            name = item.name
            if filtered_top_level is not None and name not in filtered_top_level:
                continue

            dest_path = resolved_project_path / name
            try:
                if dest_path == item.resolve():
                    continue
            except FileNotFoundError:
                pass

            if preserve_existing_specs and name == ".specs" and dest_path.exists():
                _copytree_preserve(item, dest_path)
                continue

            if item.is_dir():
                shutil.copytree(item, dest_path, dirs_exist_ok=True)
            else:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_path)

    try:
        if not is_current_dir:
            project_path.mkdir(parents=True, exist_ok=True)

        if tracker and local_template_dir is None:
            tracker.add("zip-list", "Archive contents")

        if local_template_dir is not None:
            extracted_items = list(local_template_dir.iterdir())
            if tracker:
                tracker.start("zip-list", _tag("listing"))
                tracker.complete("zip-list", _tag(f"{len(extracted_items)} items"))
            payload_root = local_template_dir
        else:
            temp_dir_ctx = tempfile.TemporaryDirectory()
            temp_dir = Path(temp_dir_ctx.name)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_contents = zip_ref.namelist()
                if tracker:
                    tracker.start("zip-list", _tag("listing"))
                    tracker.complete("zip-list", _tag(f"{len(zip_contents)} entries"))
                elif verbose:
                    console.print(f"[cyan]ZIP contains {len(zip_contents)} items[/cyan]")
                zip_ref.extractall(temp_dir)
            extracted_items = list(temp_dir.iterdir())
            payload_root = temp_dir

        flatten_applied = False
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            payload_root = extracted_items[0]
            flatten_applied = True

        if flatten_applied:
            if tracker:
                tracker.add("flatten", "Flatten nested directory")
                tracker.complete("flatten", _tag("applied"))
            elif verbose:
                console.print("[cyan]Flattened nested directory structure[/cyan]")

        _merge_into_project(payload_root)

        if tracker:
            tracker.start("extracted-summary", _tag("summarizing"))
            tracker.complete("extracted-summary", _tag(f"{len(list(payload_root.iterdir()))} payload items"))
        elif verbose:
            console.print(f"[cyan]Template files copied to {project_path}[/cyan]")

    except Exception as e:
        if tracker:
            tracker.error("extract", _tag(str(e)))
        else:
            if verbose:
                console.print(f"[red]Error extracting template:[/red] {e}")
                if debug:
                    console.print(Panel(str(e), title="Extraction Error", border_style="red"))
        if not is_current_dir and project_path.exists():
            shutil.rmtree(project_path)
        raise typer.Exit(1)
    else:
        if tracker:
            tracker.complete("extract", _tag("done"))
    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()

        if cleanup_zip and zip_path and zip_path.exists():
            zip_path.unlink()
            if tracker:
                tracker.complete("cleanup", _tag("Removed downloaded archive"))
            elif verbose:
                console.print(f"Cleaned up: {zip_path.name}")
        elif using_local_template:
            if tracker:
                tracker.skip("cleanup", _tag("Local template retained"))

    return project_path


def ensure_executable_scripts(project_path: Path, tracker: StepTracker | None = None) -> None:
    """Ensure POSIX .sh scripts under .specs/.specify/scripts (recursively) have execute bits (no-op on Windows)."""
    if os.name == "nt":
        return  # Windows: skip silently
    scripts_root = specify_scripts_dir(project_path)
    if not scripts_root.is_dir():
        return
    failures: list[str] = []
    updated = 0
    for script in scripts_root.rglob("*.sh"):
        try:
            if script.is_symlink() or not script.is_file():
                continue
            try:
                with script.open("rb") as f:
                    if f.read(2) != b"#!":
                        continue
            except Exception:
                continue
            st = script.stat(); mode = st.st_mode
            if mode & 0o111:
                continue
            new_mode = mode
            if mode & 0o400: new_mode |= 0o100
            if mode & 0o040: new_mode |= 0o010
            if mode & 0o004: new_mode |= 0o001
            if not (new_mode & 0o100):
                new_mode |= 0o100
            os.chmod(script, new_mode)
            updated += 1
        except Exception as e:
            failures.append(f"{script.relative_to(scripts_root)}: {e}")
    if tracker:
        detail = f"{updated} updated" + (f", {len(failures)} failed" if failures else "")
        tracker.add("chmod", "Set script permissions recursively")
        (tracker.error if failures else tracker.complete)("chmod", detail)
    else:
        if updated:
            console.print(f"[cyan]Updated execute permissions on {updated} script(s) recursively[/cyan]")
        if failures:
            console.print("[yellow]Some scripts could not be updated:[/yellow]")
            for f in failures:
                console.print(f"  - {f}")


def relocate_non_agent_directories(project_path: Path, tracker: StepTracker | None = None) -> None:
    """Move legacy non-agent directories into the consolidated .specs/.specify/ root."""
    specs_root = get_specs_root(project_path)
    specify_root = get_specify_root(project_path)

    # Migrate from legacy .specify directory if present
    legacy_root = project_path / ".specify"
    migrated = 0
    if legacy_root.is_dir():
        for item in legacy_root.iterdir():
            dest = specify_root / item.name
            if dest.exists():
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    for child in item.iterdir():
                        target = dest / child.name
                        if target.exists():
                            continue
                        shutil.move(str(child), str(target))
                else:
                    continue
            else:
                shutil.move(str(item), str(dest))
            migrated += 1
        try:
            legacy_root.rmdir()
        except OSError:
            pass

    non_agent_dirs = [
        "plan",
        "spec",
        "notes",
        "scratch",
        "memory",
        "docs",
        "logs",
        "specs",
    ]

    moved = 0
    for name in non_agent_dirs:
        source = project_path / name
        if not source.exists():
            continue
        destination = specify_root / name
        if destination.exists():
            continue
        shutil.move(str(source), str(destination))
        moved += 1

    nested_moved = 0
    for item in specs_root.iterdir():
        if item.name == ".specify":
            continue
        dest = specify_root / item.name
        try:
            if dest.exists():
                if item.is_dir() and dest.is_dir():
                    for child in item.iterdir():
                        target = dest / child.name
                        if target.exists():
                            continue
                        shutil.move(str(child), str(target))
                    item.rmdir()
                else:
                    continue
            else:
                shutil.move(str(item), str(dest))
                nested_moved += 1
        except Exception:
            continue

    if tracker:
        detail_parts = []
        if migrated:
            detail_parts.append(f"legacy {migrated}")
        if moved:
            detail_parts.append(f"moved {moved}")
        if nested_moved:
            detail_parts.append(f"nested {nested_moved}")
        if detail_parts:
            tracker.complete("relocate", ", ".join(detail_parts))
        else:
            tracker.skip("relocate", "no changes needed")
@app.command()
def init(
    project_name: str = typer.Argument(None, help="Name for your new project directory (optional if using --here)"),
    ai_assistants: Optional[List[str]] = typer.Option(
        None,
        "--ai",
        help="AI assistant(s) to use. Repeat --ai for multiple, or use a quoted comma-separated list "
             "(e.g., --ai \"claude, copilot\"). Choices: "
             "claude, gemini, copilot, cursor, qwen, opencode, codex, windsurf, kilocode, auggie, or roo",
    ),
    script_type: str = typer.Option(None, "--script", help="Script type to use: sh or ps"),
    ignore_agent_tools: bool = typer.Option(False, "--ignore-agent-tools", help="Skip checks for AI agent tools like Claude Code"),
    no_git: bool = typer.Option(False, "--no-git", help="Skip git repository initialization"),
    here: bool = typer.Option(False, "--here", help="Initialize project in the current directory instead of creating a new one"),
    force: bool = typer.Option(False, "--force", help="Force merge/overwrite when using --here (skip confirmation)"),
    skip_tls: bool = typer.Option(False, "--skip-tls", help="Skip SSL/TLS verification (not recommended)"),
    debug: bool = typer.Option(False, "--debug", help="Show verbose diagnostic output for network and extraction failures"),
    github_token: str = typer.Option(None, "--github-token", help="GitHub token to use for API requests (or set GH_TOKEN or GITHUB_TOKEN environment variable)"),
    template_repo: Optional[str] = typer.Option(
        None,
        "--template-repo",
    help="Override template repository in owner/repo form (defaults to Jrakru/spec-kit or SPEC_KIT_TEMPLATE_REPO)",
    ),
    template_path: Optional[Path] = typer.Option(
        None,
        "--template-path",
        help="Use a local template ZIP or directory instead of downloading (or set SPEC_KIT_TEMPLATE_PATH)",
    ),
):
    """
    Initialize a new Specify project from the latest template.
    
    This command will:
    1. Check that required tools are installed (git is optional)
    2. Let you choose your AI assistant(s) (Claude Code, Gemini CLI, GitHub Copilot, Cursor, Qwen Code, opencode, Codex CLI, Windsurf, Kilo Code, Auggie CLI, or Roo Code)
    3. Download the appropriate template from GitHub
    4. Extract the template to a new project directory or current directory
    5. Initialize a fresh git repository (if not --no-git and no existing repo)
    6. Optionally set up AI assistant commands
    
    Examples:
        specify init my-project
        specify init my-project --ai claude
        specify init my-project --ai gemini
        specify init my-project --ai copilot --no-git
        specify init my-project --ai claude --ai windsurf
        specify init my-project --ai "claude, windsurf, copilot"
        specify init my-project --ai cursor
        specify init my-project --ai qwen
        specify init my-project --ai opencode
        specify init my-project --ai codex
        specify init my-project --ai windsurf
        specify init my-project --ai auggie
        specify init --ignore-agent-tools my-project
        specify init --here --ai claude
        specify init --here --ai codex
        specify init --here
        specify init --here --force  # Skip confirmation when current directory not empty
    """
    # Show banner first
    show_banner()
    
    # Validate arguments
    if here and project_name:
        console.print("[red]Error:[/red] Cannot specify both project name and --here flag")
        raise typer.Exit(1)
    
    if not here and not project_name:
        console.print("[red]Error:[/red] Must specify either a project name or use --here flag")
        raise typer.Exit(1)
    
    # Determine project directory
    if here:
        project_name = Path.cwd().name
        project_path = Path.cwd()
        
        # Check if current directory has any files
        existing_items = list(project_path.iterdir())
        if existing_items:
            console.print(f"[yellow]Warning:[/yellow] Current directory is not empty ({len(existing_items)} items)")
            console.print("[yellow]Template files will be merged with existing content and may overwrite existing files[/yellow]")
            if force:
                console.print("[cyan]--force supplied: skipping confirmation and proceeding with merge[/cyan]")
            else:
                # Ask for confirmation
                response = typer.confirm("Do you want to continue?")
                if not response:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    raise typer.Exit(0)
    else:
        project_path = Path(project_name).resolve()
        # Check if project directory already exists
        if project_path.exists():
            error_panel = Panel(
                f"Directory '[cyan]{project_name}[/cyan]' already exists\n"
                "Please choose a different project name or remove the existing directory.",
                title="[red]Directory Conflict[/red]",
                border_style="red",
                padding=(1, 2)
            )
            console.print()
            console.print(error_panel)
            raise typer.Exit(1)
    
    # Create formatted setup info with column alignment
    current_dir = Path.cwd()
    
    setup_lines = [
        "[cyan]Specify Project Setup[/cyan]",
        "",
        f"{'Project':<15} [green]{project_path.name}[/green]",
        f"{'Working Path':<15} [dim]{current_dir}[/dim]",
    ]
    
    # Add target path only if different from working dir
    if not here:
        setup_lines.append(f"{'Target Path':<15} [dim]{project_path}[/dim]")
    
    console.print(Panel("\n".join(setup_lines), border_style="cyan", padding=(1, 2)))
    
    # Check git only if we might need it (not --no-git)
    # Only set to True if the user wants it and the tool is available
    should_init_git = False
    if not no_git:
        should_init_git = check_tool("git", "https://git-scm.com/downloads")
        if not should_init_git:
            console.print("[yellow]Git not found - will skip repository initialization[/yellow]")

    # AI assistant selection
    selected_ais = parse_ai_option_values(ai_assistants)

    if not selected_ais:
        if sys.stdin.isatty():
            selected_primary = select_with_arrows(
                AI_CHOICES,
                "Choose your AI assistant:",
                "copilot",
            )
            selected_ais = [selected_primary]
            remaining = [key for key in AI_CHOICES if key not in selected_ais]
            while remaining and typer.confirm("Add another AI assistant?", default=False):
                next_choice = select_with_arrows(
                    {key: AI_CHOICES[key] for key in remaining},
                    "Choose another AI assistant:",
                    remaining[0],
                )
                selected_ais.append(next_choice)
                remaining = [key for key in AI_CHOICES if key not in selected_ais]
        else:
            selected_ais = ["copilot"]

    normalized_ais: List[str] = []
    for ai_key in selected_ais:
        if ai_key not in AI_CHOICES:
            console.print(
                f"[red]Error:[/red] Invalid AI assistant '{ai_key}'. Choose from: {', '.join(AI_CHOICES.keys())}"
            )
            raise typer.Exit(1)
        if ai_key not in normalized_ais:
            normalized_ais.append(ai_key)

    selected_ais = normalized_ais or ["copilot"]
    
    # Check agent tools unless ignored
    if not ignore_agent_tools:
        for ai_key in selected_ais:
            agent_tool_missing = False
            install_url = ""
            if ai_key == "claude":
                if not check_tool("claude", "https://docs.anthropic.com/en/docs/claude-code/setup"):
                    install_url = "https://docs.anthropic.com/en/docs/claude-code/setup"
                    agent_tool_missing = True
            elif ai_key == "gemini":
                if not check_tool("gemini", "https://github.com/google-gemini/gemini-cli"):
                    install_url = "https://github.com/google-gemini/gemini-cli"
                    agent_tool_missing = True
            elif ai_key == "qwen":
                if not check_tool("qwen", "https://github.com/QwenLM/qwen-code"):
                    install_url = "https://github.com/QwenLM/qwen-code"
                    agent_tool_missing = True
            elif ai_key == "opencode":
                if not check_tool("opencode", "https://opencode.ai"):
                    install_url = "https://opencode.ai"
                    agent_tool_missing = True
            elif ai_key == "codex":
                if not check_tool("codex", "https://github.com/openai/codex"):
                    install_url = "https://github.com/openai/codex"
                    agent_tool_missing = True
            elif ai_key == "auggie":
                if not check_tool(
                    "auggie",
                    "https://docs.augmentcode.com/cli/setup-auggie/install-auggie-cli",
                ):
                    install_url = "https://docs.augmentcode.com/cli/setup-auggie/install-auggie-cli"
                    agent_tool_missing = True
            # GitHub Copilot, Cursor, Windsurf, and similar IDE agents do not require CLI checks

            if agent_tool_missing:
                error_panel = Panel(
                    f"[cyan]{ai_key}[/cyan] not found\n"
                    f"Install with: [cyan]{install_url}[/cyan]\n"
                    f"{AI_CHOICES[ai_key]} is required to continue with this project type.\n\n"
                    "Tip: Use [cyan]--ignore-agent-tools[/cyan] to skip this check",
                    title="[red]Agent Detection Error[/red]",
                    border_style="red",
                    padding=(1, 2)
                )
                console.print()
                console.print(error_panel)
                raise typer.Exit(1)
    
    # Determine script type (explicit, interactive, or OS default)
    if script_type:
        if script_type not in SCRIPT_TYPE_CHOICES:
            console.print(f"[red]Error:[/red] Invalid script type '{script_type}'. Choose from: {', '.join(SCRIPT_TYPE_CHOICES.keys())}")
            raise typer.Exit(1)
        selected_script = script_type
    else:
        # Auto-detect default
        default_script = "ps" if os.name == "nt" else "sh"
        # Provide interactive selection similar to AI if stdin is a TTY
        if sys.stdin.isatty():
            selected_script = select_with_arrows(SCRIPT_TYPE_CHOICES, "Choose script type (or press Enter)", default_script)
        else:
            selected_script = default_script
    
    selected_agent_labels = [AI_CHOICES[key] for key in selected_ais]
    console.print(f"[cyan]Selected AI assistant(s):[/cyan] {human_join(selected_agent_labels)}")
    console.print(f"[cyan]Selected script type:[/cyan] {selected_script}")

    # Determine template source overrides
    env_template_repo = os.getenv("SPEC_KIT_TEMPLATE_REPO")
    env_template_path = os.getenv("SPEC_KIT_TEMPLATE_PATH")

    # Default to this fork's main repo unless overridden via CLI or env
    repo_spec = template_repo or env_template_repo or "Jrakru/spec-kit"
    try:
        repo_owner, repo_name = repo_spec.split("/", 1)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid template repo '{repo_spec}'. Expected 'owner/repo'.")
        raise typer.Exit(1)

    template_path_value: Optional[Path]
    if template_path is not None:
        template_path_value = template_path.expanduser().resolve()
    elif env_template_path:
        template_path_value = Path(env_template_path).expanduser().resolve()
    else:
        template_path_value = None

    if template_path_value:
        console.print(f"[cyan]Template source override:[/cyan] {template_path_value}")
        if len(selected_ais) > 1 and template_path_value.is_file():
            console.print(
                "[red]Error:[/red] When supplying multiple AI assistants, --template-path must point to a directory "
                "containing agent-specific templates."
            )
            raise typer.Exit(1)
    elif repo_owner != "github" or repo_name != "spec-kit":
        console.print(f"[cyan]Template repo override:[/cyan] {repo_owner}/{repo_name}")
    
    # Download and set up project
    # New tree-based progress (no emojis); include earlier substeps
    tracker = StepTracker("Initialize Specify Project")
    # Flag to allow suppressing legacy headings
    sys._specify_tracker_active = True
    # Pre steps recorded as completed before live rendering
    tracker.add("precheck", "Check required tools")
    tracker.complete("precheck", "ok")
    tracker.add("ai-select", "Select AI assistant")
    tracker.complete("ai-select", human_join(selected_agent_labels))
    tracker.add("script-select", "Select script type")
    tracker.complete("script-select", selected_script)
    for key, label in [
        ("fetch", "Fetch latest release"),
        ("download", "Download template"),
        ("extract", "Extract template"),
        ("zip-list", "Archive contents"),
        ("extracted-summary", "Extraction summary"),
        ("relocate", "Consolidate non-agent assets"),
        ("chmod", "Ensure scripts executable"),
        ("cleanup", "Cleanup"),
        ("git", "Initialize git repository"),
        ("final", "Finalize")
    ]:
        tracker.add(key, label)

    # Use transient so live tree is replaced by the final static render (avoids duplicate output)
    with Live(tracker.render(), console=console, refresh_per_second=8, transient=True) as live:
        tracker.attach_refresh(lambda: live.update(tracker.render()))
        try:
            # Create a httpx client with verify based on skip_tls
            verify = not skip_tls
            local_ssl_context = ssl_context if verify else False
            local_client = httpx.Client(verify=local_ssl_context)

            existing_specs_present = (project_path / ".specs").exists()
            completed_agents: list[str] = []

            for idx, ai_key in enumerate(selected_ais, start=1):
                agent_root = AGENT_ROOT_NAMES.get(ai_key)
                top_level = None
                if idx > 1 and agent_root:
                    top_level = [agent_root]

                preserve_specs = False
                if idx == 1 and existing_specs_present:
                    preserve_specs = True
                elif idx > 1 and not agent_root:
                    preserve_specs = True

                agent_label = f"{AI_CHOICES[ai_key]} ({idx}/{len(selected_ais)})"

                download_and_extract_template(
                    project_path,
                    ai_key,
                    selected_script,
                    here,
                    verbose=False,
                    tracker=tracker,
                    client=local_client,
                    debug=debug,
                    github_token=github_token,
                    template_repo=(repo_owner, repo_name),
                    template_path=template_path_value,
                    tracker_agent_label=agent_label,
                    top_level_filter=top_level,
                    preserve_existing_specs=preserve_specs,
                )

                completed_agents.append(ai_key)
                existing_specs_present = existing_specs_present or (project_path / ".specs").exists()
                if tracker:
                    progress_note = f"{len(completed_agents)}/{len(selected_ais)} agents"
                    for key in ("download", "extract", "zip-list", "extracted-summary"):
                        tracker.complete(key, progress_note)

            # Consolidate non-agent assets under .specs/.specify
            tracker.start("relocate")
            relocate_non_agent_directories(project_path, tracker=tracker)

            # Ensure scripts are executable (POSIX)
            ensure_executable_scripts(project_path, tracker=tracker)

            # Git step
            if not no_git:
                tracker.start("git")
                if is_git_repo(project_path):
                    tracker.complete("git", "existing repo detected")
                elif should_init_git:
                    if init_git_repo(project_path, quiet=True):
                        tracker.complete("git", "initialized")
                    else:
                        tracker.error("git", "init failed")
                else:
                    tracker.skip("git", "git not available")
            else:
                tracker.skip("git", "--no-git flag")

            tracker.complete("final", "project ready")
        except Exception as e:
            tracker.error("final", str(e))
            console.print(Panel(f"Initialization failed: {e}", title="Failure", border_style="red"))
            if debug:
                _env_pairs = [
                    ("Python", sys.version.split()[0]),
                    ("Platform", sys.platform),
                    ("CWD", str(Path.cwd())),
                ]
                _label_width = max(len(k) for k, _ in _env_pairs)
                env_lines = [f"{k.ljust(_label_width)} → [bright_black]{v}[/bright_black]" for k, v in _env_pairs]
                console.print(Panel("\n".join(env_lines), title="Debug Environment", border_style="magenta"))
            if not here and project_path.exists():
                shutil.rmtree(project_path)
            raise typer.Exit(1)
        finally:
            # Force final render
            pass

    # Final static tree (ensures finished state visible after Live context ends)
    console.print(tracker.render())
    console.print("\n[bold green]Project ready.[/bold green]")
    
    # Agent folder security notice
    agent_folder_entries = [
        (ai_key, AGENT_DIRECTORY_MAP[ai_key])
        for ai_key in selected_ais
        if ai_key in AGENT_DIRECTORY_MAP
    ]

    if agent_folder_entries:
        folder_lines = "\n".join(
            f"- [cyan]{folder}[/cyan] ({AI_CHOICES[ai_key]})"
            for ai_key, folder in agent_folder_entries
        )
        security_notice = Panel(
            "Some agents may store credentials, auth tokens, or other identifying artifacts in your project.\n"
            "Consider adding the following directories (or subsets) to [cyan].gitignore[/cyan]:\n"
            f"{folder_lines}",
            title="[yellow]Agent Folder Security[/yellow]",
            border_style="yellow",
            padding=(1, 2)
        )
        console.print()
        console.print(security_notice)
    
    # Boxed "Next steps" section
    steps_lines = []
    if not here:
        steps_lines.append(f"1. Go to the project folder: [cyan]cd {project_name}[/cyan]")
        step_num = 2
    else:
        steps_lines.append("1. You're already in the project directory!")
        step_num = 2

    # Add Codex-specific setup step if needed
    if "codex" in selected_ais:
        codex_path = project_path / ".codex"
        quoted_path = shlex.quote(str(codex_path))
        if os.name == "nt":  # Windows
            cmd = f"setx CODEX_HOME {quoted_path}"
        else:  # Unix-like systems
            cmd = f"export CODEX_HOME={quoted_path}"
        
        steps_lines.append(f"{step_num}. Set [cyan]CODEX_HOME[/cyan] environment variable before running Codex: [cyan]{cmd}[/cyan]")
        step_num += 1

    # Dynamically discover available slash commands from the selected agent's folder
    def _agent_command_dir(ai: str) -> tuple[Path, str, list[str]]:
        """Return (directory, format, patterns) for command files of a given agent.
        format is one of: md, prompt.md, toml (used for parsing descriptions).
        patterns is a list of glob patterns to enumerate commands.
        """
        base = project_path
        if ai == "claude":
            return (base / ".claude/commands", "md", ["*.md"])
        if ai == "cursor":
            return (base / ".cursor/commands", "md", ["*.md"])
        if ai == "opencode":
            return (base / ".opencode/command", "md", ["*.md"])
        if ai == "windsurf":
            return (base / ".windsurf/workflows", "md", ["*.md"])
        if ai == "gemini":
            return (base / ".gemini/commands", "toml", ["*.toml"])
        if ai == "qwen":
            return (base / ".qwen/commands", "toml", ["*.toml"])
        if ai == "copilot":
            return (base / ".github/prompts", "prompt.md", ["*.prompt.md"])
        if ai == "codex":
            return (base / ".codex/prompts", "md", ["*.md"])
        if ai == "kilocode":
            return (base / ".kilocode/workflows", "md", ["*.md"])
        if ai == "auggie":
            return (base / ".augment/commands", "md", ["*.md"])
        if ai == "roo":
            return (base / ".roo/commands", "md", ["*.md"])
        # Fallback to Claude-like layout
        return (base / ".claude/commands", "md", ["*.md"])

    def _parse_description(path: Path, fmt: str) -> str | None:
        """Extract a short description from a command file by format."""
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                # Read a small header chunk
                head = f.read(1000)
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            return None
        # Normalize newlines
        head = head.replace("\r\n", "\n").replace("\r", "\n")
        if fmt in ("md", "prompt.md"):
            # Look for YAML frontmatter: --- ... description: ... ---
            if head.lstrip().startswith("---"):
                # Take lines until the second '---'
                fm = []
                lines = head.split("\n")
                dash_count = 0
                for ln in lines:
                    if ln.strip() == "---":
                        dash_count += 1
                        if dash_count == 2:
                            break
                        continue
                    if dash_count == 1:
                        fm.append(ln)
                for ln in fm:
                    if ln.strip().lower().startswith("description:"):
                        return ln.split(":", 1)[1].strip().strip('"').strip("'")
        elif fmt == "toml":
            for ln in head.split("\n")[:20]:
                s = ln.strip()
                if s.startswith("description") and "=" in s:
                    try:
                        return s.split("=", 1)[1].strip().strip('"').strip("'")
                    except Exception:
                        return None
        return None

    def _discover_commands(ai: str) -> list[tuple[str, str | None]]:
        cmd_dir, fmt, patterns = _agent_command_dir(ai)
        candidates: list[Path] = []
        for pat in patterns:
            candidates.extend(sorted(cmd_dir.glob(pat)))
        items: list[tuple[str, str | None]] = []
        for p in candidates:
            if not p.is_file():
                continue
            name = p.stem
            # For copilot .prompt.md -> strip .prompt suffix
            if fmt == "prompt.md" and name.endswith(".prompt"):
                name = name[:-7]
            desc = _parse_description(p, fmt)
            items.append((name, desc))
        return items

    discovered_commands = {
        ai_key: _discover_commands(ai_key) for ai_key in selected_ais
    }
    # Sort with a preferred core order first, then alphabetical
    core_order = [
        "constitution",
        "specify",
        "clarify",
        "plan",
        "tasks",
        "analyze",
        "implement",
    ]
    steps_lines.append(f"{step_num}. Start using slash commands with your AI assistant(s):")
    sub_idx = 1
    for ai_key in selected_ais:
        commands = discovered_commands.get(ai_key, [])
        if not commands:
            continue
        core = [c for c in commands if c[0] in core_order]
        extra = [c for c in commands if c[0] not in core_order]
        core.sort(key=lambda x: core_order.index(x[0]))
        extra.sort(key=lambda x: x[0])
        ordered = core + extra
        agent_label = AI_CHOICES.get(ai_key, ai_key)
        steps_lines.append(f"   {step_num}.{sub_idx} {agent_label} commands:")
        for name, desc in ordered:
            if desc:
                steps_lines.append(f"      - [cyan]/{name}[/] - {desc}")
            else:
                steps_lines.append(f"      - [cyan]/{name}[/]")
        sub_idx += 1

    steps_panel = Panel("\n".join(steps_lines), title="Next Steps", border_style="cyan", padding=(1,2))
    console.print()
    console.print(steps_panel)

    if "codex" in selected_ais:
        warning_text = """[bold yellow]Important Note:[/bold yellow]

Custom prompts do not yet support arguments in Codex. You may need to manually specify additional project instructions directly in prompt files located in [cyan].codex/prompts/[/cyan].

For more information, see: [cyan]https://github.com/openai/codex/issues/2890[/cyan]"""
        
        warning_panel = Panel(warning_text, title="Slash Commands in Codex", border_style="yellow", padding=(1,2))
        console.print()
        console.print(warning_panel)

@app.command()
def check():
    """Check that all required tools are installed."""
    show_banner()
    console.print("[bold]Checking for installed tools...[/bold]\n")

    tracker = StepTracker("Check Available Tools")
    
    tracker.add("git", "Git version control")
    tracker.add("claude", "Claude Code CLI")
    tracker.add("gemini", "Gemini CLI")
    tracker.add("qwen", "Qwen Code CLI")
    tracker.add("code", "Visual Studio Code")
    tracker.add("code-insiders", "Visual Studio Code Insiders")
    tracker.add("cursor-agent", "Cursor IDE agent")
    tracker.add("windsurf", "Windsurf IDE")
    tracker.add("kilocode", "Kilo Code IDE")
    tracker.add("opencode", "opencode")
    tracker.add("codex", "Codex CLI")
    tracker.add("auggie", "Auggie CLI")
    
    git_ok = check_tool_for_tracker("git", tracker)
    claude_ok = check_tool_for_tracker("claude", tracker)  
    gemini_ok = check_tool_for_tracker("gemini", tracker)
    qwen_ok = check_tool_for_tracker("qwen", tracker)
    code_ok = check_tool_for_tracker("code", tracker)
    code_insiders_ok = check_tool_for_tracker("code-insiders", tracker)
    cursor_ok = check_tool_for_tracker("cursor-agent", tracker)
    windsurf_ok = check_tool_for_tracker("windsurf", tracker)
    kilocode_ok = check_tool_for_tracker("kilocode", tracker)
    opencode_ok = check_tool_for_tracker("opencode", tracker)
    codex_ok = check_tool_for_tracker("codex", tracker)
    auggie_ok = check_tool_for_tracker("auggie", tracker)

    console.print(tracker.render())

    console.print("\n[bold green]Specify CLI is ready to use![/bold green]")

    if not git_ok:
        console.print("[dim]Tip: Install git for repository management[/dim]")
    if not (claude_ok or gemini_ok or cursor_ok or qwen_ok or windsurf_ok or kilocode_ok or opencode_ok or codex_ok or auggie_ok):
        console.print("[dim]Tip: Install an AI assistant for the best experience[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
