#!/usr/bin/env bash
# Install agents-farm in its own virtual environment, and add a short command (default: af).
#
#   scripts/install.sh                  install from this checkout, command: agents-farm and af
#   scripts/install.sh --name farm      use another short name
#   scripts/install.sh --no-alias       install only `agents-farm`
#   scripts/install.sh --uninstall      remove what this script installed
#   scripts/install.sh --dry-run        show the plan and the collision checks, change nothing
#
# Safe by design: it never overwrites a file or command that is not its own, it does not
# edit your shell config or ~/.claude/settings.json, and it only removes what it created.
# Works with the bash 3.2 that ships with macOS.
set -euo pipefail

APP="agents-farm"
REPO_URL="https://github.com/mythes/agents-farm"
MARKER=".agents-farm-install"

NAME="af"
ALIAS=1
BIN_DIR="${HOME}/.local/bin"
PREFIX="${HOME}/.local/share/agents-farm"
REF="main"
FROM_GIT=0
EDITABLE=0
FORCE=0
DRY=0
UNINSTALL=0

say()  { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: install.sh [options]

  --name NAME      short command name (default: af). Letters, digits, - and _
  --no-alias       do not create a short command
  --bin-dir DIR    where the commands go (default: ~/.local/bin)
  --prefix DIR     where the virtual environment goes (default: ~/.local/share/agents-farm)
  --from-git       install from GitHub instead of this checkout
  --ref REF        git branch or tag for --from-git (default: main)
  --editable       install this checkout in editable mode (for development)
  --force          replace an existing '$APP' command that this script did not create
  --dry-run        show the plan and the collision checks, change nothing
  --uninstall      remove the commands and the virtual environment
  -h, --help       show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name)      [ $# -ge 2 ] || die "--name needs a value"; NAME="$2"; shift 2 ;;
    --no-alias)  ALIAS=0; shift ;;
    --bin-dir)   [ $# -ge 2 ] || die "--bin-dir needs a value"; BIN_DIR="$2"; shift 2 ;;
    --prefix)    [ $# -ge 2 ] || die "--prefix needs a value"; PREFIX="$2"; shift 2 ;;
    --from-git)  FROM_GIT=1; shift ;;
    --ref)       [ $# -ge 2 ] || die "--ref needs a value"; REF="$2"; FROM_GIT=1; shift 2 ;;
    --editable)  EDITABLE=1; shift ;;
    --force)     FORCE=1; shift ;;
    --dry-run)   DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)   usage; exit 0 ;;
    *)           usage >&2; die "unknown option: $1" ;;
  esac
done

TARGET="$PREFIX/venv/bin/$APP"   # every command we create is a symlink to this file

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  [ -n "$PREFIX" ] && [ "$PREFIX" != "/" ] && [ "$PREFIX" != "$HOME" ] || die "refusing to use prefix '$PREFIX'"
  removed=0
  for f in "$BIN_DIR"/*; do
    if [ -L "$f" ] && [ "$(readlink "$f")" = "$TARGET" ]; then
      if [ "$DRY" = 1 ]; then say "would remove $f"; else rm "$f"; say "removed $f"; fi
      removed=$((removed + 1))
    fi
  done
  if [ -f "$PREFIX/$MARKER" ]; then
    if [ "$DRY" = 1 ]; then say "would remove $PREFIX/venv"; else
      rm -rf "${PREFIX:?}/venv" "${PREFIX:?}/$MARKER"
      rmdir "$PREFIX" 2>/dev/null || true
      say "removed $PREFIX/venv"
    fi
  else
    say "no install found in $PREFIX (nothing to remove there)"
  fi
  say "Not touched: your data in ~/.agents-farm and any hooks you added to ~/.claude/settings.json."
  exit 0
fi

# ------------------------------------------------------------------ checks
if [ "$ALIAS" = 1 ]; then
  [[ "$NAME" =~ ^[A-Za-z][A-Za-z0-9_-]*$ ]] || die "invalid --name '$NAME': use letters, digits, - and _, and start with a letter"
  [ "$NAME" != "$APP" ] || ALIAS=0
fi

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$(command -v "$cand")"; break
  fi
done
[ -n "$PY" ] || die "Python 3.9 or newer is required, but none was found"

# Where does the code come from: this checkout, or GitHub.
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
SRC=""
if [ "$FROM_GIT" = 0 ] && [ -n "$SCRIPT_DIR" ] && grep -q "^name = \"$APP\"" "$SCRIPT_DIR/../pyproject.toml" 2>/dev/null; then
  SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
  SOURCE_TEXT="this checkout ($SRC)"
else
  command -v git >/dev/null 2>&1 || die "git is required to install from GitHub"
  [ "$EDITABLE" = 0 ] || die "--editable needs a local checkout"
  SRC="git+$REPO_URL.git@$REF"
  SOURCE_TEXT="GitHub ($REPO_URL, ref $REF)"
fi

is_ours() { [ -L "$1" ] && [ "$(readlink "$1")" = "$TARGET" ]; }

# 1. the main command
MAIN_NOTE="will be created"
if [ -e "$BIN_DIR/$APP" ] || [ -L "$BIN_DIR/$APP" ]; then
  if is_ours "$BIN_DIR/$APP"; then MAIN_NOTE="will be updated"
  elif [ "$FORCE" = 1 ]; then MAIN_NOTE="will be REPLACED (--force)"
  else die "$BIN_DIR/$APP already exists and was not created by this script. Use --force to replace it, or --bin-dir to choose another folder"
  fi
fi
OTHER_MAIN="$(command -v "$APP" 2>/dev/null || true)"
if [ -n "$OTHER_MAIN" ] && [ "$OTHER_MAIN" != "$BIN_DIR/$APP" ]; then
  warn "another '$APP' is on your PATH: $OTHER_MAIN (the first one on PATH wins)"
fi

# 2. the short name: find every kind of collision before we create anything
ALIAS_NOTE=""
if [ "$ALIAS" = 1 ]; then
  ALIAS_NOTE="will be created"
  if [ -e "$BIN_DIR/$NAME" ] || [ -L "$BIN_DIR/$NAME" ]; then
    if is_ours "$BIN_DIR/$NAME"; then ALIAS_NOTE="will be updated"
    else ALIAS_NOTE="SKIPPED: $BIN_DIR/$NAME already exists and is not ours"
    fi
  else
    existing="$(command -v "$NAME" 2>/dev/null || true)"
    if [ -n "$existing" ]; then
      ALIAS_NOTE="SKIPPED: '$NAME' is already a command or shell builtin ($existing)"
    else
      for rc in .zshrc .zprofile .zshenv .bashrc .bash_profile .profile; do
        if [ -f "$HOME/$rc" ] && grep -Eq "^[[:space:]]*(alias[[:space:]]+$NAME=|function[[:space:]]+$NAME([[:space:]]|\\(|\$)|$NAME[[:space:]]*\\(\\))" "$HOME/$rc"; then
          ALIAS_NOTE="SKIPPED: '$NAME' is defined as an alias or function in ~/$rc"
          break
        fi
      done
    fi
  fi
fi

say "agents-farm install plan"
say "  source:   $SOURCE_TEXT"
say "  python:   $PY"
say "  venv:     $PREFIX/venv"
say "  command:  $BIN_DIR/$APP  ($MAIN_NOTE)"
if [ "$ALIAS" = 1 ]; then say "  short:    $BIN_DIR/$NAME  ($ALIAS_NOTE)"; else say "  short:    none"; fi

case "$ALIAS_NOTE" in
  SKIPPED*) warn "the short command '$NAME' will NOT be created. Choose another name with --name (for example: --name farm), or remove the conflict first." ;;
esac

if [ "$DRY" = 1 ]; then say "dry run: nothing was changed"; exit 0; fi

# ----------------------------------------------------------------- install
[ -n "$PREFIX" ] && [ "$PREFIX" != "/" ] && [ "$PREFIX" != "$HOME" ] || die "refusing to use prefix '$PREFIX'"
mkdir -p "$PREFIX" "$BIN_DIR"
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  "$PY" -m venv "$PREFIX/venv"
fi
: > "$PREFIX/$MARKER"
VENV_PY="$PREFIX/venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip
if [ "$EDITABLE" = 1 ]; then
  "$VENV_PY" -m pip install --quiet --upgrade -e "$SRC"
else
  "$VENV_PY" -m pip install --quiet --upgrade "$SRC"
  "$VENV_PY" -m pip install --quiet --force-reinstall --no-deps "$SRC"   # refresh the code even if the version did not change
fi
"$TARGET" --help >/dev/null 2>&1 || die "the installed command does not run: $TARGET"

ln -sfn "$TARGET" "$BIN_DIR/$APP"
RUN_CMD="$APP"
if [ "$ALIAS" = 1 ]; then
  case "$ALIAS_NOTE" in
    SKIPPED*) ;;
    *) ln -sfn "$TARGET" "$BIN_DIR/$NAME"; RUN_CMD="$NAME" ;;
  esac
fi

say ""
say "Installed: $APP $("$VENV_PY" -c 'import agents_farm; print(agents_farm.__version__)')"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on your PATH. Add this line to your shell config (~/.zshrc or ~/.bashrc):"
     say "  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
say "Try it:      $RUN_CMD --demo"
say "The exact 'waiting' status works with no setup. Hooks are optional: they add the text of a request ('$RUN_CMD hooks-snippet', see the README)."
say "Uninstall:   scripts/install.sh --uninstall"
