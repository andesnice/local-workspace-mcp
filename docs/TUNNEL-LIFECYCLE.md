# Runtime-only tunnel / 常駐通道改用專用版

The long-lived connection uses the **official `tunnel-client-runtime` v0.0.15 or newer**.
The full `tunnel-client` remains a setup/diagnostic CLI (`init`, `doctor`); it is not the
background executable. Both are available from [OpenAI releases](https://github.com/openai/tunnel-client/releases/tag/v0.0.15).
Verify the downloaded archive against that release's SHA256SUMS.txt.

## Why / 修正原因

The full CLI starts an optional Codex app-server. Its startup failure loop can retry without delay,
and failed initialization can leave a child process alive. A source regression test against upstream
v0.0.15 reproduced 155 failed starts in 350 ms when the executable was missing.
That proves a defect exists; it does not establish the cause of every reported CPU spike.

上游官方 `pkg/runtimeapp` 不包含 Codex bridge、管理 UI 或外掛管理。改用 runtime 是移除
不需要的執行路徑，不是把高 CPU 程序定時重啟，也不需要自行修改官方二進位檔。
這裡的 runtime 專用版不會縮減 Local Workspace MCP 的文件／完整模式工具。

## New installations / 新安裝

Keep `tunnel-client` and `tunnel-client-runtime` side by side. The connection wizard uses the full CLI
to prepare and diagnose the profile, then launches only a binary advertising `flavor=runtime`.
A different location can be supplied with `--runtime-client`. The saved receipt contains paths and
tunnel ID only; no key value. The login installer likewise rejects a full CLI as the runtime.

## Existing installations / 既有安裝

1. Keep a backup of the existing service definition and executable. Stop the existing foreground or
   login service before replacing its runtime; never start two clients for the same tunnel.
2. Keep the private profile/key and MCP command. Point the service's executable argument to the verified
   official `tunnel-client-runtime`. If a local supervisor exists, update its child executable instead.
3. Restart and check `/healthz`, `/readyz`, the actual child process tree and an ordinary ChatGPT tool call.
   MCP Python/Node workers are expected; a tunnel-owned `codex app-server` is not. Runtime has no `/ui`.

自動啟動程式仍可保留原本名稱與隱藏狀態。健康監測可作備援，但不是這個修正的替代品。
長期穩定性仍需要實際使用觀察；若再次出現高 CPU，應保留當次程序與堆疊證據。

## Dependency audit compatibility

The lockfile refresh updates `brace-expansion` (1.1.21 / 2.1.7), `fast-uri` (3.1.8)
and `ip-address` (10.7.3). Desktop Commander stays pinned to 0.2.50.
`md-to-pdf` alone overrides `chokidar` to 4.0.3 to remove the unpatched `braces`
dependency ([advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)).
The MCP PDF API does not use the CLI watcher. Chokidar v4 retains CommonJS and
exact-file watching but removes glob expansion; when using the optional md-to-pdf
CLI directly, pass explicit filenames (or shell-expanded globs), not quoted glob
patterns. A regression test loads the PDF API and observes an actual file change,
including a filename containing literal braces. No audit exclusions are used.
