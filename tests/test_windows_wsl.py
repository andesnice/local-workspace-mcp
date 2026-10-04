import os
import runpy
import subprocess
from pathlib import Path

import pytest

BRIDGE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/windows_wsl.py"))
main = BRIDGE["main"]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo space 測試"
    repo.mkdir()
    state = tmp_path / "private"
    state.mkdir(mode=0o700)
    workspace = tmp_path / "documents space 測試"
    calls = []
    monkeypatch.setitem(main.__globals__, "REPO", repo)
    monkeypatch.setitem(main.__globals__, "validate_environment", lambda: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="ext2/ext3\n")

    monkeypatch.setattr(subprocess, "run", run)
    return repo, state, workspace, calls


@pytest.mark.parametrize("arguments", [
    ["install", "--mode", "full"],
    ["install", "--skip-worker"],
    ["connect", "--accept-full-permissions"],
    ["connect", "--mode", "full", "--accept-full-permissions"],
])
def test_permission_errors_do_not_start_processes(setup, arguments):
    assert main(arguments) == 1
    assert setup[3] == []


def test_documents_install_preserves_paths_and_uses_existing_installer(setup):
    repo, state, workspace, calls = setup
    assert main(["install", "--state", str(state), "--workspace", str(workspace)]) == 0
    assert calls[-2][0] == ["docker", "info"]
    command, options = calls[-1]
    assert command[1:] == [str(repo / "scripts/install.py"), "--state", str(state),
                           "--workspace", str(workspace), "--mode", "documents", "--no-register"]
    assert options == {"cwd": repo}


def test_accepted_full_without_worker_does_not_probe_docker(setup):
    repo, state, workspace, calls = setup
    assert main(["install", "--state", str(state), "--workspace", str(workspace),
                 "--mode", "full", "--accept-full-permissions", "--skip-worker"]) == 0
    assert not any(command[0] == "docker" for command, _ in calls)
    assert calls[-1][0][-3:] == ["full", "--no-register", "--skip-worker"]


def test_docker_failure_prevents_install(setup, monkeypatch):
    _, state, workspace, calls = setup
    original = subprocess.run

    def run(command, **kwargs):
        if command[0] == "docker":
            raise subprocess.CalledProcessError(1, command)
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    assert main(["install", "--state", str(state), "--workspace", str(workspace)]) == 1
    assert not any("install.py" in str(command) for command, _ in calls)


def test_connect_uses_installed_python_and_existing_interactive_wizard(setup):
    repo, state, _, calls = setup
    interpreter = repo / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    (state / "launch.sh").touch()
    assert main(["connect", "--state", str(state)]) == 0
    assert calls[-1][0] == [str(interpreter), str(repo / "scripts/connect_chatgpt.py"),
                            "--state", str(state), "--interactive", "--run"]


def test_connect_does_not_install_missing_environment(setup):
    _, state, _, calls = setup
    assert main(["connect", "--state", str(state)]) == 1
    assert all(command[0] == "stat" for command, _ in calls)


def test_child_failure_is_returned(setup, monkeypatch):
    _, state, workspace, _ = setup
    original = subprocess.run

    def run(command, **kwargs):
        if "scripts/install.py" in command[1]:
            return subprocess.CompletedProcess(command, 17)
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    assert main(["install", "--state", str(state), "--workspace", str(workspace)]) == 17


@pytest.mark.parametrize("location", ["repo", "state", "home"])
def test_overlapping_workspace_is_rejected(setup, location):
    repo, state, _, calls = setup
    workspace = {"repo": repo / "files", "state": state, "home": Path.home()}[location]
    assert main(["install", "--state", str(state), "--workspace", str(workspace)]) == 1
    assert calls == []


def test_windows_filesystem_is_rejected_before_install(setup, monkeypatch):
    _, state, workspace, _ = setup
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(
        command, 0, stdout="9p\n"))
    assert main(["install", "--state", str(state), "--workspace", str(workspace)]) == 1


@pytest.mark.parametrize("system,release,uid", [
    ("Windows", "11", 1000), ("Linux", "microsoft", 1000),
    ("Linux", "6.6-microsoft-standard-WSL2", 0),
])
def test_native_windows_wsl1_and_root_are_rejected(monkeypatch, system, release, uid):
    validate = BRIDGE["validate_environment"]
    monkeypatch.setattr(validate.__globals__["platform"], "system", lambda: system)
    monkeypatch.setattr(validate.__globals__["platform"], "release", lambda: release)
    monkeypatch.setattr(os, "getuid", lambda: uid, raising=False)
    with pytest.raises(ValueError):
        validate()


def test_bootstrap_keeps_repository_out_of_python_source(tmp_path, monkeypatch):
    # Execute the same fixed bootstrap used by PowerShell, with adversarial path characters.
    repo = tmp_path / "space 測試 ';$(not-a-command)"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "windows_wsl.py").write_text("import sys; print(repr(sys.argv[1:]))\n")
    source = (Path(__file__).resolve().parents[1] / "scripts/windows.ps1").read_text()
    bootstrap = source.split('$bootstrap = "', 1)[1].split('"', 1)[0]
    result = subprocess.run([os.sys.executable, "-c", bootstrap, str(repo), "connect", "--state", "~/state"],
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "['connect', '--state', '~/state']"
