#!/bin/sh
set -eu

REPO_URL="https://github.com/Clueless-Creations/jev-ios-ultrafast.git"
INSTALL_DIR="${JEV_IOS_HOME:-$HOME/.jev-ios-ultrafast}"
BIN_DIR="${JEV_IOS_BIN_DIR:-$HOME/.local/bin}"

command -v python3 >/dev/null 2>&1 || { echo "python3 is required (3.11+)." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
elif [ -e "$INSTALL_DIR" ]; then
  echo "$INSTALL_DIR already exists and is not a git checkout." >&2
  exit 1
else
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install -q -e "$INSTALL_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/.venv/bin/jev-ios" "$BIN_DIR/jev-ios"

echo
echo "Installed jev-ios to $BIN_DIR/jev-ios"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add $BIN_DIR to PATH, for example: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo
"$BIN_DIR/jev-ios" doctor
