import os
import runpy
import subprocess
from pathlib import Path

import pytest

CONNECT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/connect_chatgpt.py"))
configure = CONNECT["configure"]
prepare_config = CONNECT["prepare_config"]
load_connection = CONNECT["load_connection"]
save_connection = CONNECT["save_connection"]
main = CONNECT["main"]
validate_runtime_key = CONNECT["validate_runtime_key"]


@pytest.mark.parametrize("key", [
    "sk-test-secret-000000000000" * 2,
    "sk-test-secret-000000000000sk-other-secret-000000000000",
    "sk-test-secret-000000000000\nextra",
])
def test_repeated_or_multiline_key_is_rejected_before_writes(tmp_path, key):
    state = tmp_path / "not-created"
    with pytest.raises(ValueError) as error:
        configure(state, tmp_path / "client", TUNNEL_ID, key)
    assert key not in str(error.value)
    assert not state.exists()


def test_single_runtime_key_is_accepted():
    validate_runtime_key("sk-test-secret-000000000000")


SAMPLE = """control_plane:
  tunnel_id: tunnel_0123456789abcdef0123456789abcdef
  api_key: ${OPENAI_API_KEY}
health:
  listen_addr: 127.0.0.1:0
mcp:
  command: /private/launch.sh
"""
TUNNEL_ID = "tunnel_0123456789abcdef0123456789abcdef"


def test_prepare_config_references_private_key_without_embedding_it(tmp_path):
    result = prepare_config(SAMPLE, tmp_path / "runtime-key", tmp_path / "health.url")
    assert f'api_key: "file:{tmp_path / "runtime-key"}"' in result
    assert f'url_file: "{tmp_path / "health.url"}"' in result
    assert result.count("url_file:") == 1
    with pytest.raises(ValueError, match="格式已變更"):
        prepare_config(SAMPLE.replace("api_key:", "credential:"), tmp_path / "key", tmp_path / "url")


def test_configure_keeps_existing_profile_on_unknown_official_layout(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    launch = state / "launch.sh"
    launch.write_text("#!/bin/sh\n")
    launch.chmod(0o700)
    profiles = state / "tunnel-profiles"
    profiles.mkdir(mode=0o700)
    config = profiles / "local-workspace.yaml"
    config.write_text("existing: true\n")
    config.chmod(0o600)
    client = tmp_path / "tunnel-client"
    client.write_text("")
    client.chmod(0o700)

    def fake_run(command, **_kwargs):
        Path(command[command.index("--profile-dir") + 1], "local-workspace.yaml").write_text(
            SAMPLE.replace("api_key:", "credential:")
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="格式已變更"):
        configure(state, client, TUNNEL_ID, "sk-test-secret-000000000000")
    assert config.read_text() == "existing: true\n"
    assert not (state / "runtime-key").exists()


def test_configure_stores_secret_privately_and_runs_doctor(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    launch = state / "launch.sh"
    launch.write_text("#!/bin/sh\n")
    launch.chmod(0o700)
    client = tmp_path / "tunnel-client"
    client.write_text("")
    client.chmod(0o700)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "init" in command:
            Path(command[command.index("--profile-dir") + 1], "local-workspace.yaml").write_text(SAMPLE)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = configure(state, client, TUNNEL_ID, "sk-test-secret-000000000000")
    key = state / "runtime-key"
    assert key.read_text() == "sk-test-secret-000000000000\n"
    assert "sk-test-secret" not in config.read_text()
    assert os.stat(key).st_mode & 0o077 == 0
    assert os.stat(config).st_mode & 0o077 == 0
    assert calls[-1][1] == "doctor"
    assert configure(state, client, TUNNEL_ID, None) == config


def test_failed_doctor_leaves_no_new_key_or_profile(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    launch = state / "launch.sh"
    launch.write_text("#!/bin/sh\n")
    launch.chmod(0o700)
    client = tmp_path / "tunnel-client"
    client.write_text("")
    client.chmod(0o700)

    def fake_run(command, **_kwargs):
        if "init" in command:
            Path(command[command.index("--profile-dir") + 1], "local-workspace.yaml").write_text(SAMPLE)
        else:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        configure(state, client, TUNNEL_ID, "sk-test-secret-000000000000")
    assert not (state / "runtime-key").exists()
    assert not (state / "tunnel-profiles/local-workspace.yaml").exists()


def test_connection_receipt_keeps_only_nonsecret_reuse_values(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    client = tmp_path / "tunnel-client"
    save_connection(state, client, TUNNEL_ID)
    receipt = state / "connection.json"
    assert load_connection(state) == {"tunnel_client": str(client), "tunnel_id": TUNNEL_ID}
    assert "runtime-key" not in receipt.read_text()
    assert os.stat(receipt).st_mode & 0o077 == 0


def test_second_double_click_reuses_connection_without_key_prompt(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    launch = state / "launch.sh"
    launch.write_text("#!/bin/sh\n")
    launch.chmod(0o700)
    key = state / "runtime-key"
    key.write_text("sk-existing-private-key\n")
    key.chmod(0o600)
    client = tmp_path / "tunnel-client"
    client.write_text("")
    client.chmod(0o700)
    runtime = tmp_path / "tunnel-client-runtime"
    runtime.write_text("")
    runtime.chmod(0o700)
    save_connection(state, client, TUNNEL_ID, runtime)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "init" in command:
            Path(command[command.index("--profile-dir") + 1], "local-workspace.yaml").write_text(SAMPLE)
        return subprocess.CompletedProcess(command, 0, stdout="0.0.15 flavor=runtime")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("unexpected interactive prompt"))
    assert main(["--interactive", "--run", "--state", str(state)]) == 0
    assert calls[-1][:2] == [str(runtime), "run"]
    assert key.read_text() == "sk-existing-private-key\n"


@pytest.mark.parametrize("version", ["0.0.15 flavor=full", "0.0.15 flavor=runtime-cloudflared", ""])
def test_reject_full_client_for_running_connection(tmp_path, monkeypatch, version):
    client = tmp_path / "tunnel-client"
    client.touch()
    client.chmod(0o700)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout=version))
    with pytest.raises(ValueError, match="tunnel-client-runtime"):
        CONNECT["resolve_runtime"](str(client), client, False)


def test_runtime_discovery_beside_setup_client(tmp_path, monkeypatch):
    client = tmp_path / "tunnel-client"
    runtime = tmp_path / "tunnel-client-runtime"
    runtime.touch()
    runtime.chmod(0o700)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="0.0.15 git sha: example flavor=runtime"))
    assert CONNECT["resolve_runtime"](None, client, False) == runtime
