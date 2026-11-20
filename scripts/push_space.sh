#!/bin/sh
# Publishes the current commit to the Hugging Face Space.
#
#   sh scripts/push_space.sh            (pushes to the git remote named "space")
#
# The Space needs two things the GitHub repo shouldn't carry: Space config (YAML) at the top of
# README.md, and the deploy requirements as requirements.txt. Both go into a throwaway commit that
# is pushed only to the Space, so the GitHub history stays clean.
set -e
REMOTE="${1:-space}"
ROOT="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
git -C "$ROOT" worktree add --detach "$TMP" HEAD >/dev/null
# Remove the temporary checkout however the script ends, including a failed push.
trap 'cd "$ROOT"; git worktree remove --force "$TMP" 2>/dev/null; git worktree prune' EXIT
cd "$TMP"
cp requirements-space.txt requirements.txt
{
  cat <<'YAML'
---
title: OrderPal
emoji: 🍱
colorFrom: red
colorTo: gray
sdk: gradio
sdk_version: 6.32.0
python_version: "3.12"
app_file: hf_space.py
pinned: false
license: apache-2.0
short_description: Agentic support-resolution engine for food delivery
---

YAML
  cat README.md
} > README.space.md && mv README.space.md README.md
git add -A
git commit -q -m "Hugging Face Space build of $(git rev-parse --short HEAD)"
git push --force "$REMOTE" HEAD:main
echo "Pushed. Watch the build in the Space's Logs tab."
