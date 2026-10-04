#!/usr/bin/env python3
"""Guide a local installation through the private ChatGPT tunnel setup."""

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TUNNEL_ID = re.compile(r"tunnel_[0-9a-f]{32}\Z")


def validate_runtime_key(key: str) -> None:
    """Reject accidental repeated pastes without exposing credential contents."""
    if (not key.startswith("sk-") or len(key) < 20
            or key.count("sk-") != 1 or any(char.isspace() for char in key)):
        raise ValueError("金鑰格式不正確，或重複貼上；請只貼上一次。沒有修改通道設定。")


def prepare_config(sample: str, key_file: Path, health_file: Path) -> str:
    """Patch only the expected official sample fields; reject an unfamiliar layout."""
    lines = sample.splitlines()
    section = None
    sections = []
    key_count = 0
    health_count = 0
    url_count = 0
    result = []
    for line in lines:
        top_level = re.match(r"^([a-z][a-z0-9_]*):(?:\s|$)", line)
        if top_level:
            if section == "health" and url_count == 0:
                result.append("  url_file: " + json.dumps(str(health_file)))
                url_count += 1
            section = top_level.group(1)
            sections.append(section)
            if section == "health":
                health_count += 1
        if section == "control_plane" and re.match(r"^\s+api_key:\s*", line):
            line = "  api_key: " + json.dumps("file:" + str(key_file))
            key_count += 1
        if section == "health" and re.match(r"^\s+url_file:\s*", line):
            line = "  url_file: " + json.dumps(str(health_file))
            url_count += 1
        result.append(line)
    if section == "health" and url_count == 0:
        result.append("  url_file: " + json.dumps(str(health_file)))
        url_count += 1
    if sections.count("control_plane") != 1 or health_count != 1 or key_count != 1 or url_count != 1:
        raise ValueError("官方通道設定格式已變更；既有設定沒有被修改。")
    return "\n".join(result) + "\n"


def require_private_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError(f"私有檔案權限必須是 0600：{path}")


def resolve_client(value: str | None, interactive: bool) -> Path:
    candidate = value or shutil.which("tunnel-client")
    if not candidate and interactive:
        candidate = input("官方 tunnel-client 執行檔路徑：").strip()
    if not candidate:
        raise ValueError("請先下載官方 tunnel-client，再輸入執行檔路徑。")
    path = Path(candidate).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"找不到可執行的 tunnel-client：{path}")
    return path


def resolve_runtime(value: str | None, client: Path, interactive: bool) -> Path:
    """Long-lived connections use the official narrow runtime, never the full CLI."""
    suffix = ".exe" if client.suffix == ".exe" else ""
    candidate = value or str(client.with_name("tunnel-client-runtime" + suffix))
    if not Path(candidate).expanduser().is_file() and interactive:
        candidate = input("官方 tunnel-client-runtime 執行檔路徑：").strip()
    runtime = resolve_client(candidate, False)
    result = subprocess.run([str(runtime), "--version"], capture_output=True, text=True,
                            check=True, timeout=10)
    if "flavor=runtime" not in result.stdout.split():
        raise ValueError("請使用官方 tunnel-client-runtime；完整 tunnel-client 僅用於設定與診斷。")
    return runtime


def load_connection(state: Path) -> dict[str, str]:
    receipt = state / "connection.json"
    if not receipt.exists():
        return {}
    require_private_file(receipt)
    value = json.loads(receipt.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"連線紀錄格式不正確：{receipt}")
    client = value.get("tunnel_client")
    tunnel_id = value.get("tunnel_id")
    if not isinstance(client, str) or not isinstance(tunnel_id, str) or not TUNNEL_ID.fullmatch(tunnel_id):
        raise ValueError(f"連線紀錄格式不正確：{receipt}")
    result = {"tunnel_client": client, "tunnel_id": tunnel_id}
    runtime = value.get("runtime_client")
    if runtime is not None:
        if not isinstance(runtime, str):
            raise ValueError(f"連線紀錄的 runtime_client 格式不正確：{receipt}")
        result["runtime_client"] = runtime
    return result


def save_connection(state: Path, client: Path, tunnel_id: str, runtime: Path | None = None) -> None:
    receipt = state / "connection.json"
    if receipt.exists():
        require_private_file(receipt)
    descriptor, temporary = tempfile.mkstemp(prefix="connection-", dir=state)
    try:
        with os.fdopen(descriptor, "w") as stream:
            data = {"tunnel_client": str(client), "tunnel_id": tunnel_id}
            if runtime is not None:
                data["runtime_client"] = str(runtime)
            json.dump(data, stream)
            stream.write("\n")
        os.replace(temporary, receipt)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(state: Path, client: Path, tunnel_id: str, key: str | None) -> Path:
    if key is not None:
        validate_runtime_key(key)
    if not TUNNEL_ID.fullmatch(tunnel_id):
        raise ValueError("通道 ID 格式應是 tunnel_ 加 32 位小寫十六進位字元。")
    launch = state / "launch.sh"
    if not launch.is_file() or not os.access(launch, os.X_OK):
        raise ValueError(f"請先執行 Install.command；找不到 launch.sh：{launch}")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state.stat().st_mode & 0o077:
        raise ValueError(f"私有設定資料夾權限過寬：{state}")
    profiles = state / "tunnel-profiles"
    profiles.mkdir(mode=0o700, exist_ok=True)
    if profiles.stat().st_mode & 0o077:
        raise ValueError(f"通道設定資料夾權限過寬：{profiles}")
    key_file = state / "runtime-key"
    config = profiles / "local-workspace.yaml"
    if key_file.exists():
        require_private_file(key_file)
        if key:
            raise ValueError("已有 runtime key；精靈不會自動覆寫。")
    elif not key:
        raise ValueError("請先建立只允許 Tunnels Read + Use 的 runtime key。")

    created_key = False
    created_config = False
    try:
        with tempfile.TemporaryDirectory(prefix="tunnel-setup-", dir=state) as scratch_name:
            scratch = Path(scratch_name)
            subprocess.run(
                [str(client), "init", "--sample", "sample_mcp_stdio_local", "--profile", "local-workspace",
                 "--profile-dir", str(scratch), "--tunnel-id", tunnel_id, "--mcp-command", str(launch),
                 "--health-listen-addr", "127.0.0.1:0"],
                check=True, timeout=30,
            )
            generated = scratch / "local-workspace.yaml"
            prepared = prepare_config(generated.read_text(), key_file, state / "tunnel-health.url")
            if config.exists():
                require_private_file(config)
                if config.read_text() != prepared:
                    raise ValueError(f"已有不同的通道設定；請先檢查，不會覆寫：{config}")
            if key:
                descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created_key = True
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(key + "\n")
            if not config.exists():
                descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created_config = True
                with os.fdopen(descriptor, "w") as stream:
                    stream.write(prepared)
            require_private_file(key_file)
            require_private_file(config)
        print("私有設定已儲存，正在使用官方程式檢查通道……")
        subprocess.run([str(client), "doctor", "--config", str(config)], check=True, timeout=90)
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if created_config:
            config.unlink()
        if created_key:
            key_file.unlink()
        raise
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true", help="Prompt for paths and tunnel ID")
    parser.add_argument("--state", type=Path, help="Private state directory used during installation")
    parser.add_argument("--tunnel-client", help="Path to the official tunnel-client executable")
    parser.add_argument("--runtime-client", help="Official tunnel-client-runtime for the running connection")
    parser.add_argument("--tunnel-id", help="ID created in OpenAI Platform (not a secret)")
    parser.add_argument("--run", action="store_true", help="Run the tunnel after a successful doctor check")
    args = parser.parse_args(argv)
    try:
        if args.interactive:
            print("將本機工具連接到一般 ChatGPT 對話。")
        if args.interactive and args.state is None:
            default = REPO / ".local/state"
            args.state = Path(input(f"私有設定資料夾 [{default}]：").strip() or str(default))
        if args.state is None:
            parser.error("請提供 --state，或使用 --interactive。")
        state = args.state.expanduser().resolve()
        previous = load_connection(state)
        if args.interactive and not previous:
            print("請先建立通道和只允許 Tunnels Read + Use 的 runtime key：")
            print("https://platform.openai.com/settings/organization/tunnels")
            print("https://platform.openai.com/settings/organization/api-keys")
        elif args.interactive:
            print("找到上次的通道 ID 與用戶端路徑；金鑰仍只存於私有檔案。")
        client = resolve_client(args.tunnel_client or previous.get("tunnel_client"), args.interactive)
        runtime = resolve_runtime(
            args.runtime_client or previous.get("runtime_client"), client, args.interactive
        )
        tunnel_id = args.tunnel_id or previous.get("tunnel_id")
        if args.interactive and tunnel_id is None:
            tunnel_id = input("通道 ID（tunnel_...）：").strip()
        if not tunnel_id or not TUNNEL_ID.fullmatch(tunnel_id):
            raise ValueError("請從 OpenAI Platform 複製 tunnel_ 通道 ID；這裡不要貼 API key。")
        key_file = state / "runtime-key"
        key = None
        if not key_file.exists():
            if not sys.stdin.isatty():
                raise ValueError("請在互動式終端機輸入金鑰，避免金鑰進入命令列記錄。")
            print("下一行只貼上一次金鑰，再按 Enter。畫面不顯示字元是正常的，請勿重複貼上。")
            key = getpass.getpass("Runtime key（隱藏輸入）：").strip()
            validate_runtime_key(key)
        config = configure(state, client, tunnel_id, key)
        save_connection(state, client, tunnel_id, runtime)
        print("官方診斷通過。使用 ChatGPT 時請保持這個指令運作：")
        print("  " + shlex.join([str(runtime), "run", "--config", str(config)]))
        print("接著在 ChatGPT 建立並連接外掛，依 docs/CHATGPT.md 做真實工具測試。")
        if args.run:
            print("正在啟動通道；使用 ChatGPT 時請保持此視窗開啟。")
            subprocess.run([str(runtime), "run", "--config", str(config)], check=True)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"連線設定未完成：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n通道已停止。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
