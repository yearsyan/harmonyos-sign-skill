#!/bin/bash
# ============================================================
# 一键安装 harmonyos-signing skill 到各 Agent 工具
#
# 用法（三种模式）:
#   1) 远程安装（公开仓库，无需 git，推荐）:
#        curl -sL https://raw.githubusercontent.com/yearsyan/harmonyos-sign-skill/main/install.sh | bash
#   2) 本地仓库执行:
#        git clone git@github.com:yearsyan/harmonyos-sign-skill.git
#        cd harmonyos-sign-skill && ./install.sh          # git clone 源
#        cd harmonyos-sign-skill && ./install.sh --local  # 本地复制（离线）
#   3) 指定仓库地址:
#        ./install.sh <git-url>
#
# 环境变量: HOS_SKILL_REPO 覆盖下载/克隆源（默认 GitHub 公开仓库）
#
# 支持的 Agent 工具（检测目录存在与否，自动跳过未安装的）:
#   pi           ~/.pi/agent/skills/
#   Claude Code  ~/.claude/skills/
#   Codex CLI    ~/.codex/skills/
#   Kimi Code    $KIMI_CODE_HOME/skills/ (默认 ~/.kimi-code/skills/)
#   ZCode        ~/.zcode/skills/
# ============================================================
set -e
NAME="harmonyos-signing"
REPO="${HOS_SKILL_REPO:-https://github.com/yearsyan/harmonyos-sign-skill.git}"
TARBALL_URL="${HOS_SKILL_TARBALL:-https://codeload.github.com/yearsyan/harmonyos-sign-skill/tar.gz/refs/heads/main}"
RAW_URL="https://raw.githubusercontent.com/yearsyan/harmonyos-sign-skill/main"

# ---- 源准备：本地目录 / git clone / 远程下载 ----
SRC_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
LOCAL=0
if [ "$1" = "--local" ]; then
  LOCAL=1
  REPO=""
elif [ -n "$1" ] && [ "$1" != "--local" ]; then
  REPO="$1"
fi

# 管道执行检测（curl | bash 时 $0 不是脚本文件）
if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/SKILL.md" ]; then
  LOCAL=0
  echo "== 远程模式：从公开仓库下载 =="
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if command -v curl >/dev/null; then
    curl -sL "$TARBALL_URL" | tar xz -C "$TMP"
  elif command -v wget >/dev/null; then
    wget -qO- "$TARBALL_URL" | tar xz -C "$TMP"
  else
    echo "错误: 需要 curl 或 wget"; exit 1
  fi
  SRC_DIR="$(find "$TMP" -maxdepth 2 -name SKILL.md -printf '%h\n' | head -1)"
  [ -n "$SRC_DIR" ] || { echo "错误: 下载失败"; exit 1; }
fi

# ---- 安装到各工具 ----
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
    git clone --depth 1 "$REPO" "$target" 2>/dev/null \
      || { echo "    clone 失败，改用远程下载"; _download_to "$target"; }
  else
    echo "  - 安装到 $target（本地复制）"
    cp -r "$SRC_DIR" "$target"; rm -rf "$target/.git"
  fi
}

_download_to() {
  local target="$1"
  mkdir -p "$target"
  if command -v curl >/dev/null; then
    curl -sL "$TARBALL_URL" | tar xz --strip-components=1 -C "$target"
  elif command -v wget >/dev/null; then
    wget -qO- "$TARBALL_URL" | tar xz --strip-components=1 -C "$target"
  else
    echo "    (无 curl/wget，跳过)"
    rm -rf "$target"
    return 1
  fi
}

echo "== 安装 $NAME skill =="
echo "源: ${REPO:-<本地复制>} ${LOCAL:+[local]}"
install_to "$HOME/.pi/agent/skills"
install_to "$HOME/.claude/skills"
install_to "$HOME/.codex/skills"
install_to "${KIMI_CODE_HOME:-$HOME/.kimi-code}/skills"
install_to "$HOME/.zcode/skills"
echo
echo "完成。重启对应工具会话后生效，可通过 /skill:harmonyos-signing 调用。"
echo "（ZCode 需在 Settings -> Skills 点 Refresh）"