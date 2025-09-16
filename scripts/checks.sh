#!/usr/bin/env bash
set -euo pipefail

python_supports_pcbnew() {
  local interpreter="$1"
  if [ -z "$interpreter" ]; then
    return 1
  fi

  if [ -x "$interpreter" ]; then
    "$interpreter" - <<'PY' >/dev/null 2>&1 || return 1
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("pcbnew") else 1)
PY
    return 0
  fi

  if ! command -v "$interpreter" >/dev/null 2>&1; then
    return 1
  fi

  "$interpreter" - <<'PY' >/dev/null 2>&1 || return 1
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("pcbnew") else 1)
PY
  return 0
}

has_pcbnew() {
  local -a candidates=()
  local candidate
  local seen=""

  if [ -n "${SUGARKUBE_PCBNEW_PYTHON:-}" ]; then
    candidates+=("$SUGARKUBE_PCBNEW_PYTHON")
  fi
  candidates+=(python python3 /usr/bin/python3 python3.13 python3.12 python3.11 python3.10)

  for candidate in "${candidates[@]}"; do
    [ -z "$candidate" ] && continue
    case " $seen " in
      *" $candidate "*)
        continue
        ;;
    esac
    seen+=" $candidate"

    if python_supports_pcbnew "$candidate"; then
      SUGARKUBE_PCBNEW_PYTHON="$candidate"
      export SUGARKUBE_PCBNEW_PYTHON
      return 0
    fi
  done

  return 1
}

is_kicad_path() {
  case "$1" in
    *.kicad_pro|*.kicad_pcb|*.kicad_sch|*.kicad_sym|*.kicad_mod|*.kicad_prl|*.kicad_wks)
      return 0
      ;;
    *.sch|*.lib|*.dcm|*.kicad_dru|*.kicad_step|*.net|*.cmp|*.kicad_rename)
      return 0
      ;;
    *.pretty/*.kicad_mod|.kibot/*)
      return 0
      ;;
  esac
  return 1
}

contains_kicad_path() {
  local input="$1"
  if [ -z "$input" ]; then
    return 1
  fi

  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if is_kicad_path "$path"; then
      return 0
    fi
  done <<<"$input"

  return 1
}

detect_kicad_activity() {
  if [ "${SUGARKUBE_FORCE_KICAD_INSTALL:-}" = "1" ]; then
    return 0
  fi

  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi

  local status_output
  status_output="$(git status --porcelain --untracked-files=all 2>/dev/null || true)"
  if [ -n "$status_output" ]; then
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      local path
      path="${line#?? }"
      path="${path##* -> }"
      if is_kicad_path "$path"; then
        return 0
      fi
    done <<EOF
$status_output
EOF
  fi

  if [ -n "${CI:-}" ]; then
    local diff_output=""
    local diff_range=""
    local remote_name=""
    local base_ref=""
    local is_shallow="false"

    if git remote >/dev/null 2>&1; then
      if git remote get-url origin >/dev/null 2>&1; then
        remote_name="origin"
      else
        remote_name="$(git remote 2>/dev/null | head -n1 || true)"
      fi
    fi

    if git rev-parse --is-shallow-repository >/dev/null 2>&1; then
      is_shallow="$(git rev-parse --is-shallow-repository 2>/dev/null || echo false)"
    fi
    if [ "$is_shallow" = "true" ] && [ -n "$remote_name" ]; then
      git fetch --no-tags --deepen=64 "$remote_name" >/dev/null 2>&1 || true
    fi

    if [ -n "${GITHUB_BASE_REF:-}" ]; then
      base_ref="${GITHUB_BASE_REF}"
      if [ -n "$remote_name" ]; then
        base_ref="${remote_name}/${GITHUB_BASE_REF}"
      fi

      if ! git rev-parse --verify "$base_ref" >/dev/null 2>&1 && [ -n "$remote_name" ]; then
        local fetch_ref
        fetch_ref="refs/heads/${GITHUB_BASE_REF}:refs/remotes/${remote_name}/${GITHUB_BASE_REF}"
        git fetch --no-tags "$remote_name" "$fetch_ref" >/dev/null 2>&1 || true
      fi
      if ! git rev-parse --verify "$base_ref" >/dev/null 2>&1 && [ -n "$remote_name" ]; then
        git fetch --no-tags "$remote_name" "${GITHUB_BASE_REF}" >/dev/null 2>&1 || true
      fi
      if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
        diff_range="${base_ref}...HEAD"
      fi
    fi

    if [ -z "$diff_range" ]; then
      if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        diff_range="HEAD^..HEAD"
      elif [ "$is_shallow" = "true" ] && [ -n "$remote_name" ]; then
        git fetch --no-tags --deepen=64 "$remote_name" >/dev/null 2>&1 || true
        if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
          diff_range="HEAD^..HEAD"
        fi
      fi
    fi

    if [ -z "$diff_range" ] && [ -n "$base_ref" ]; then
      if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
        local merge_base
        merge_base="$(git merge-base "$base_ref" HEAD 2>/dev/null || true)"
        if [ -n "$merge_base" ]; then
          diff_range="${merge_base}..HEAD"
        fi
      fi
    fi

    if [ -n "$diff_range" ]; then
      diff_output="$(git diff --name-only "$diff_range" 2>/dev/null || true)"
      if contains_kicad_path "$diff_output"; then
        return 0
      fi
    fi

    local log_output
    log_output="$(git log --name-only --pretty=format: --max-count=50 HEAD 2>/dev/null || true)"
    if contains_kicad_path "$log_output"; then
      return 0
    fi
  fi

  local head_ref="${GITHUB_SHA:-}"
  if [ -n "$head_ref" ]; then
    if ! git rev-parse --verify "${head_ref}^{commit}" >/dev/null 2>&1; then
      head_ref=""
    fi
  fi
  if [ -z "$head_ref" ] && git rev-parse --verify HEAD >/dev/null 2>&1; then
    head_ref="HEAD"
  fi
  if [ -n "$head_ref" ]; then
    local head_output
    head_output="$(git show --name-only --pretty=format: "$head_ref" 2>/dev/null || true)"
    if contains_kicad_path "$head_output"; then
      return 0
    fi
  fi

  return 1
}

maybe_install_kicad() {
  if has_pcbnew; then
    return 0
  fi

  echo "KiCad 9 is required for KiBot exports; attempting automatic install" >&2

  if command -v apt-get >/dev/null 2>&1; then
    local -a apt_cmd add_repo_cmd
    if [ "$(id -u)" -ne 0 ]; then
      if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        apt_cmd=(sudo -n apt-get)
        add_repo_cmd=(sudo -n add-apt-repository)
      else
        echo "Unable to install KiCad automatically: sudo privileges are required" >&2
        return 1
      fi
    else
      apt_cmd=(apt-get)
      add_repo_cmd=(add-apt-repository)
    fi

    export DEBIAN_FRONTEND=noninteractive

    if ! command -v add-apt-repository >/dev/null 2>&1; then
      if ! "${apt_cmd[@]}" update >/dev/null 2>&1; then
        echo "apt-get update failed while preparing KiCad installation" >&2
        return 1
      fi
      if ! "${apt_cmd[@]}" install -y software-properties-common >/dev/null 2>&1; then
        echo "Failed to install software-properties-common for KiCad repository setup" >&2
        return 1
      fi
    fi

    if ! "${add_repo_cmd[@]}" --yes ppa:kicad/kicad-9.0-releases >/dev/null 2>&1; then
      echo "Failed to add the KiCad 9 APT repository" >&2
      return 1
    fi
    if ! "${apt_cmd[@]}" update >/dev/null 2>&1; then
      echo "apt-get update failed after enabling the KiCad repository" >&2
      return 1
    fi
    if ! "${apt_cmd[@]}" install -y kicad >/dev/null 2>&1; then
      echo "KiCad installation via apt-get failed" >&2
      return 1
    fi
  elif command -v brew >/dev/null 2>&1; then
    if ! brew install --cask kicad >/dev/null 2>&1; then
      if ! brew install kicad >/dev/null 2>&1; then
        echo "Homebrew installation of KiCad failed" >&2
        return 1
      fi
    fi
  else
    echo "Unsupported platform for automatic KiCad installation" >&2
    return 1
  fi

  if command -v pyenv >/dev/null 2>&1; then
    pyenv rehash >/dev/null 2>&1 || true
  fi
  hash -r

  if has_pcbnew; then
    return 0
  fi

  echo "KiCad installation completed but the pcbnew Python module is still unavailable" >&2
  return 1
}

# Ensure required Python tooling is available.  Some environments may have
# `flake8` pre-installed but lack other dependencies like `pyspelling` or
# `linkchecker`, which are needed later in this script.  Install the full set
# whenever any of these tools are missing.
if ! command -v flake8 >/dev/null 2>&1 || \
   ! command -v pyspelling >/dev/null 2>&1 || \
   ! command -v linkchecker >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system \
      flake8 isort black pytest pytest-cov coverage pyspelling linkchecker \
      >/dev/null 2>&1
  else
    pip install flake8 isort black pytest pytest-cov coverage pyspelling linkchecker \
      >/dev/null 2>&1
  fi
  if command -v pyenv >/dev/null 2>&1; then
    pyenv rehash >/dev/null 2>&1
  fi
  hash -r
fi

# Ensure KiCad 9 is installed when electronics assets change.  This keeps
# general CI jobs lightweight while automatically provisioning KiCad for
# workflows that touch `.kicad_*` or `.kibot/` files.
if detect_kicad_activity; then
  if ! maybe_install_kicad; then
    echo "KiCad is required for electronics changes but automatic installation failed" >&2
    exit 1
  fi
else
  if ! has_pcbnew; then
    echo "KiCad not installed; skipping KiBot checks" >&2
  fi
fi

# python checks
flake8 . --exclude=.venv --max-line-length=100
isort --check-only . --skip .venv
black --check . --line-length=100 --exclude ".venv/"

# js checks
if [ -f package.json ]; then
  if command -v npm >/dev/null 2>&1; then
    if [ -f package-lock.json ]; then
      npm ci
      npx playwright install --with-deps
      npm run lint
      npm run format:check
      npm test -- --coverage
    else
      echo "package-lock.json not found, skipping JS checks" >&2
    fi
  else
    echo "npm not found, skipping JS checks" >&2
  fi
fi

# run tests; treat "no tests" exit code 5 as success
if command -v pytest >/dev/null 2>&1; then
  if ! pytest --cov=. --cov-report=xml --cov-report=term -q; then
    rc=$?
    if [ "$rc" -ne 5 ]; then
      exit "$rc"
    fi
  fi
fi

# run bats tests when available
if ! command -v bats >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
      if apt-get update >/dev/null 2>&1 && \
        apt-get install -y bats >/dev/null 2>&1; then
        :
      else
        echo "bats install failed; skipping" >&2
      fi
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      if sudo -n apt-get update >/dev/null 2>&1 && \
        sudo -n apt-get install -y bats >/dev/null 2>&1; then
        :
      else
        echo "bats install failed; skipping" >&2
      fi
    else
      echo "bats not installed and no privilege to install; skipping" >&2
    fi
  elif command -v brew >/dev/null 2>&1; then
    brew install bats >/dev/null 2>&1 || true
  fi
fi
if command -v bats >/dev/null 2>&1 && ls tests/*.bats >/dev/null 2>&1; then
  bats tests/*.bats
else
  echo "bats not found or no Bats tests, skipping" >&2
fi

# docs checks
# Spell checking requires `aspell`. Attempt to install it when possible but
# continue gracefully if installation is not possible.
if ! command -v aspell >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
      if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
      else
        echo "aspell not installed and no sudo; skipping spell check" >&2
        SUDO=""
      fi
    fi
    if [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
      :
    else
      $SUDO apt-get update >/dev/null 2>&1 && \
        $SUDO apt-get install -y aspell aspell-en >/dev/null 2>&1 || \
        echo "aspell install failed; skipping" >&2
    fi
  elif command -v brew >/dev/null 2>&1; then
    brew install aspell >/dev/null 2>&1 || echo "aspell install failed; skipping" >&2
  else
    echo "aspell not found and no package manager available; skipping spell check" >&2
  fi
fi
# Only run the spell checker when both `pyspelling` and its `aspell` backend
# are available. Some environments (like minimal CI containers) do not include
# the `aspell` binary by default which would cause `pyspelling` to error. In
# those cases we silently skip the spelling check instead of failing the whole
# pre-commit run.
if command -v pyspelling >/dev/null 2>&1 && command -v aspell >/dev/null 2>&1 \
  && [ -f .spellcheck.yaml ]; then
  pyspelling -c .spellcheck.yaml
fi

if command -v linkchecker >/dev/null 2>&1; then
  if [ -f README.md ] && [ -d docs ]; then
    # Explicitly ignore external URLs so behaviour is consistent across
    # LinkChecker versions which may default to checking remote links.
    linkchecker --no-warnings --ignore-url '^https?://' README.md docs/
  else
    echo "README.md or docs/ missing, skipping link check" >&2
  fi
fi
