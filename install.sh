#!/usr/bin/env bash
# Put `aegis` on PATH.
#
# Every command in the documentation, in the task packets and in the protocols is written as
# `aegis …`. Without this the reader has to translate each one into a path relative to
# wherever the plugin happens to live — which breaks the moment the instructions are read by
# a different runner, on a different machine, or in CI.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-$HOME/.local/bin}"

mkdir -p "$target"
ln -sf "$here/scripts/aegis/aegis" "$target/aegis"
echo "linked $target/aegis -> $here/scripts/aegis/aegis"

# Verify the link we just made, not whatever `aegis` happens to be first on PATH.
if ! "$target/aegis" --help >/dev/null 2>&1; then
  echo "the installed launcher does not run; check $target/aegis" >&2
  exit 1
fi

if [ "$(command -v aegis 2>/dev/null)" != "$target/aegis" ]; then
  echo
  echo "$target/aegis is installed but another aegis comes first on PATH. Add it first:"
  echo "  echo 'export PATH=\"$target:\$PATH\"' >> ~/.zshrc && exec zsh"
  exit 0
fi

echo "verified: $(command -v aegis)"
aegis --help >/dev/null && echo "aegis is ready — run it from any project root"
