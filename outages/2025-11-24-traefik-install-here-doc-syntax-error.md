# Outage Report: Traefik install here-doc syntax regression

**Date**: 2025-11-24
**Component**: just traefik-install recipe
**Severity**: Medium (install workflow blocked)
**Status**: Resolved

## Summary

After recent November 2025 edits to `just traefik-install`, the generated shell script contained an
unterminated here-document. Running `just traefik-install` immediately failed with a bash parse
error (`here-document ... delimited by end-of-file` and `syntax error: unexpected end of file`) and
exited before any Kubernetes or Helm logic executed.

## Impact

- Developers on the 3-node HA dev cluster could not run `just traefik-install`; the command exited
  with code 2 during shell parsing.
- No Traefik install/uninstall actions reached the cluster because execution stopped before any
  kubectl or Helm calls.

## Timeline (brief)

- First attempts to run `just traefik-install` on the freshly re-imaged cluster failed with the
  here-doc syntax error.
- Inspecting `/run/user/.../traefik-install` showed the script ended without a matching `EOF` for a
  here-doc added in recent Codex edits.
- The syntax error reproduced consistently until the recipe was corrected.

## Root cause

- A new multi-line message was added to the `traefik-install` recipe using `cat <<EOF ...`, but the
  closing `EOF` marker was missing or mis-indented in the justfile, leaving the here-doc
  unterminated once expanded to a shell script.
- Bash reported the unterminated here-doc and aborted before reaching any preflight checks or Helm
  operations.

## Resolution

- Replaced the problematic here-doc block with explicit `echo` statements so every control path has
  balanced syntax.
- Added a test (`tests/test_traefik_install_script_syntax.py`) that dumps the recipe via
  `just --show` and runs `bash -n` on it, ensuring future syntax errors are caught in CI.

## Lessons learned / follow-ups

- Prefer simple `echo` sequences for short multi-line messages in just recipes unless a here-doc is
  necessary.
- For any recipe that emits non-trivial shell scripts, run `just --show <recipe> | bash -n` in CI to
  catch syntax regressions before they reach real clusters.
- Maintain preflight checks that guard cluster topology and dependencies, but ensure the shell
  structure stays minimal to avoid parse-time failures.
