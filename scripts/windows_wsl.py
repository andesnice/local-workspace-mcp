#!/usr/bin/env python3
"""Windows launcher bridge: run the existing setup scripts inside WSL2."""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def directory(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Use an absolute Linux path or ~/ path without '..'.")
    return path.resolve()


def require_linux_storage(path: Path) -> None:
    existing = path
    while not existing.exists():
        existing = existing.parent
    result = subprocess.run(
        ["stat", "-f", "-c", "%T", str(existing)], check=True, capture_output=True, text=True
    )
    if result.stdout.strip() not in {"ext2/ext3", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "zfs"}:
        raise ValueError("Keep the repository and private state on the WSL Linux filesystem.")


def validate_environment() -> None:
    if sys.version_info < (3, 12):
        raise ValueError("Python 3.12 or newer is required inside WSL.")
    if platform.system() != "Linux" or "wsl2" not in platform.release().lower():
        raise ValueError("Select a WSL2 distribution; check wsl --list --verbose.")
    if os.getuid() == 0:
        raise ValueError("Use a non-root default WSL user; do not run setup with sudo.")


def validate_paths(repo: Path, state: Path, workspace: Path | None) -> None:
    home = Path.home().resolve()
    if home not in state.parents:
        raise ValueError("Private state must be a dedicated directory under your WSL home.")
    paths = [repo, state] + ([workspace] if workspace is not None else [])
    for index, left in enumerate(paths):
        if left == Path(left.anchor) or left == home or left in home.parents or os.path.ismount(left):
            raise ValueError("Choose dedicated directories, not a home or filesystem root.")
        for right in paths[index + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("Repository, workspace and private state must not overlap.")
    require_linux_storage(repo)
    require_linux_storage(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "connect"])
    parser.add_argument("--state", default="~/.local/state/local-workspace-mcp-wsl")
    parser.add_argument("--workspace", default="~/LocalWorkspace")
    parser.add_argument("--mode", choices=["documents", "full"], default="documents")
    parser.add_argument("--accept-full-permissions", action="store_true")
    parser.add_argument("--skip-worker", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "connect" and (args.mode != "documents" or args.skip_worker
                                          or args.accept_full_permissions):
            raise ValueError("Mode and permission choices apply only to installation.")
        if args.mode == "full" and not args.accept_full_permissions:
            raise ValueError("Full mode requires --accept-full-permissions; it has WSL user permissions.")
        if args.skip_worker and args.mode != "full":
            raise ValueError("Skipping Docker requires explicitly accepted full mode.")
        validate_environment()
        state = directory(args.state)
        workspace = directory(args.workspace) if args.action == "install" else None
        validate_paths(REPO, state, workspace)
        # WSL --exec does not load shell profiles; uv is commonly installed here.
        os.environ["PATH"] = str(Path.home() / ".local/bin") + os.pathsep + os.environ.get("PATH", "")
        if args.action == "install":
            command = [sys.executable, str(REPO / "scripts/install.py"), "--state", str(state),
                       "--workspace", str(workspace), "--mode", args.mode, "--no-register"]
            if args.skip_worker:
                command.append("--skip-worker")
            else:
                subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=30)
        else:
            interpreter = REPO / ".venv/bin/python"
            if not interpreter.is_file() or not (state / "launch.sh").is_file():
                raise ValueError("Install this checkout with the selected state directory first.")
            command = [str(interpreter), str(REPO / "scripts/connect_chatgpt.py"),
                       "--state", str(state), "--interactive", "--run"]
        return subprocess.run(command, cwd=REPO).returncode
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Windows/WSL setup stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
