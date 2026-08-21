#!/bin/bash
# ============================================================
# 一键安装 harmonyos-signing skill 到各 Agent 工具
#
# 用法:
#   ./install.sh                          # 默认从 GitHub 仓库 clone
#   ./install.sh <git-url>                # 指定仓库地址（如 SSH）
#   ./install.sh --local                  # 从当前目录复制（离线/私有仓库无 key）
#
# 支持的 Agent 工具（检测目录存在与否，自动跳过未安装的）:
#   pi           ~/.pi/agent/skills/
#   Claude Code  ~/.claude/skills/
#   Codex CLI    ~/.codex/skills/
#   Kimi Code    $KIMI_CODE_HOME/skills/ (默认 ~/.kimi-code/skills/)
#   ZCode        ~/.zcode/skills/
# ============================================================
set -e
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${1:-https://github.com/yearsyan/harmonyos-sign-skill.git}"
NAME="harmonyos-signing"
if [ "$1" = "--local" ]; then
  REPO=""
fi

install_to() {
  local dir="$1"
  if [ -z "$dir" ] || [ ! -d "$dir" ]; then
    echo "  - 跳过 $dir（目录不存在）"
    return
  fi
  local target="$dir/$NAME"
  if [ -d "$target/.git" ]; then
    echo "  - 更新 $target"
    git -C "$target" pull --ff-only 2>/dev/null || git -C "$target" reset --hard origin/main 2>/dev/null || true
  elif [ -d "$target" ]; then
    echo "  - 更新（非 git）$target"
    rm -rf "$target"; cp -r "$SRC_DIR" "$target"; rm -rf "$target/.git"
  elif [ -n "$REPO" ]; then
    echo "  - 安装到 $target"
    git clone --depth 1 "$REPO" "$target" 2>/dev/null || { echo "    clone 失败，改用本地复制"; cp -r "$SRC_DIR" "$target"; rm -rf "$target/.git"; }
  else
    echo "  - 安装到 $target（本地复制）"
    cp -r "$SRC_DIR" "$target"; rm -rf "$target/.git"
  fi
}

echo "== 安装 harmonyos-signing skill =="
echo "仓库: ${REPO:-<本地复制>}"
install_to "$HOME/.pi/agent/skills"
install_to "$HOME/.claude/skills"
install_to "$HOME/.codex/skills"
install_to "${KIMI_CODE_HOME:-$HOME/.kimi-code}/skills"
install_to "$HOME/.zcode/skills"
echo
echo "完成。重启对应工具会话后生效，可通过 /skill:harmonyos-signing 调用。"
echo "（ZCode 需在 Settings -> Skills 点 Refresh）"