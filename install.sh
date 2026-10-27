#!/bin/sh
# install alles:  curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
#
# downloads only the app (no tests or docs) for one exact commit, then `alles install` builds its
# own python environment and starts it as a background service. ALLES_BRANCH picks another branch.
set -eu

repo="${ALLES_REPOSITORY:-jxherc/alles}"
branch="${ALLES_BRANCH:-main}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  accent=$(printf '\033[1;38;5;147m') good=$(printf '\033[32m') bad=$(printf '\033[31m')
  dim=$(printf '\033[2m') off=$(printf '\033[0m')
else
  accent='' good='' bad='' dim='' off=''
fi

ok() { printf '  %s✓%s %-20s%s%s%s\n' "$good" "$off" "$1" "$dim" "${2:-}" "$off"; }
fail() {
  printf '  %s✗%s %s\n\n  %s%s%s\n' "$bad" "$off" "$1" "$bad" "$2" "$off" >&2
  [ -z "${3:-}" ] || printf '  %s\n' "$3" >&2
  printf '\n' >&2
  exit 1
}
# questions read the keyboard even though this script itself arrives through a pipe
ask() {
  [ -r /dev/tty ] || return 1
  printf '  %s [Y/n] ' "$1"
  read -r answer < /dev/tty || return 1
  case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}
# fetch URL [HEADER]
fetch() {
  if command -v curl >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then curl -fsSL -H "$2" "$1"; else curl -fsSL "$1"; fi
  else
    if [ -n "${2:-}" ]; then wget -qO- --header="$2" "$1"; else wget -qO- "$1"; fi
  fi
}

printf '\n  %salles%s  install\n\n' "$accent" "$off"

case "$(uname -s)" in
  Linux | Darwin) ;;
  *) fail "system" "alles installs on linux and macos" ;;
esac
command -v tar >/dev/null 2>&1 || fail "system" "tar is missing"
command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 \
  || fail "system" "curl or wget is needed to download alles"

python=python3
if ! command -v "$python" >/dev/null 2>&1 \
  || ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  if command -v apt-get >/dev/null 2>&1; then
    fail "python" "alles needs python 3.11 or newer" "run: sudo apt install python3 python3-venv"
  fi
  fail "python" "alles needs python 3.11 or newer" "get it from python.org, or: brew install python"
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

# debian and ubuntu ship python's venv module as its own package
if ! "$python" -m venv "$tmp/venv-check" >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1 && ask "python's venv module is missing. install python3-venv now?"; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv >/dev/null 2>&1 \
      || fail "python" "could not install python3-venv"
    "$python" -m venv "$tmp/venv-check" >/dev/null 2>&1 || fail "python" "python's venv module still does not work"
    ok "venv module" "python3-venv added"
  else
    fail "python" "python's venv module is missing" "run: sudo apt install python3-venv, then this again"
  fi
fi
rm -rf "$tmp/venv-check"

commit=$(fetch "https://api.github.com/repos/$repo/commits/$branch" "Accept: application/vnd.github.sha") \
  || fail "download" "could not reach github to find the newest alles"
case "$commit" in
  *[!0-9a-f]* | "") fail "download" "github answered with something that is not a commit" ;;
esac
mkdir "$tmp/src"
fetch "https://codeload.github.com/$repo/tar.gz/$commit" | tar -xzf - -C "$tmp/src" \
  || fail "download" "the download stopped before it finished"
src=$(find "$tmp/src" -mindepth 1 -maxdepth 1 -type d | head -n 1)
[ -f "$src/cli.py" ] || fail "download" "the download is not an alles release"
ok "download" "$(printf '%s' "$commit" | cut -c1-7) from $branch"

export ALLES_INSTALL_REPOSITORY="$repo" ALLES_INSTALL_BRANCH="$branch" ALLES_INSTALL_COMMIT="$commit"
cd "$tmp"
if [ -r /dev/tty ]; then
  "$python" "$src/cli.py" install < /dev/tty
else
  "$python" "$src/cli.py" install
fi
