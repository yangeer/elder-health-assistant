#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Keep this project's sessions and profiles separate from other installations.
export DSH_HOME="${DSH_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/elder-health-harness}"
runtime_base="/root/.local/share/elder-dsh"
node_bin="${DSH_NODE:-/root/.local/share/elder-dsh-node/node_modules/node-linux-x64/bin/node}"
cli_bin="${DSH_CLI:-$runtime_base/node_modules/@deepseek-ai/dsh/lib/bin.js}"
if [[ ! -x "$node_bin" ]]; then node_bin="$(command -v node)"; fi
"$node_bin" -e 'if(Number(process.versions.node.split(".")[0])<24 || (Number(process.versions.node.split(".")[0])===24 && Number(process.versions.node.split(".")[1])<9)){console.error("DeepSeek Harness 需要 Node.js >=24.9；请配置 DSH_NODE。");process.exit(1)}'
export PATH="$(dirname -- "$node_bin"):$PATH"
if [[ ! -f "$cli_bin" ]]; then
  printf '%s\n' '找不到 Harness 运行包，请按 README-Harness.md 安装或设置 DSH_CLI。' >&2
  exit 1
fi
if [[ $# -eq 0 ]]; then set -- web --no-open; fi
if [[ "$1" == web ]]; then
  shift
  set -- web --patch "$PWD/harness-plugins/elder-audio.patch.yml" "$@"
elif [[ "$1" == --profile && "${2:-}" == web ]]; then
  shift 2
  set -- --profile web --patch "$PWD/harness-plugins/elder-audio.patch.yml" "$@"
fi
exec "$node_bin" "$cli_bin" "$@"
