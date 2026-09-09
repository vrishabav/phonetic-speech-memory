#!/usr/bin/env bash
# Finalise the submission tree.
#
# Unpacks the final version of every tracked file over this repository, removes
# everything that is no longer part of the submission, reinstalls the renamed
# package, and verifies the result.
#
# The package was renamed lmh -> psm and the project language-memory-handler ->
# phonetic-speech-memory, so the old src/lmh package and the old editable
# install are removed here. Your .env is NOT touched, and SARVAM_API_KEY is
# still the variable the live path reads.
#
# Nothing is committed. Run `git status` / `git diff` afterwards and commit
# yourself.
#
# Usage:  bash finalise.sh

set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f pyproject.toml ]]; then
  echo "error: run this from the repository directory" >&2
  exit 1
fi
if [[ ! -f psm-final.tar.gz ]]; then
  echo "error: psm-final.tar.gz is not next to this script" >&2
  exit 1
fi

echo "==> removing what is no longer part of the submission"
rm -rf docs src/lmh src/*.egg-info data .pytest_cache .ruff_cache
rm -f WORKING.md requirements-optional.txt
rm -f ./*.patch ./*.orig ./*.rej Makefile.txt lmh.bundle .lmh_write_test

echo "==> unpacking the final tree"
tar -xzf psm-final.tar.gz

echo "==> cleaning up"
rm -f psm-final.tar.gz finalise.sh

echo "==> reinstalling the renamed package"
if [[ -x .venv/bin/python ]]; then
  .venv/bin/pip uninstall -y language-memory-handler >/dev/null 2>&1 || true
  .venv/bin/pip install --quiet -e .
  PY=.venv/bin/python
else
  PY=python3
fi

echo "==> verifying"
"$PY" -m pytest -q
"$PY" -m psm.cli eval --out /tmp/psm-verify --label verify | head -3
"$PY" -m ruff check src tests evals || true
rm -rf /tmp/psm-verify

echo
echo "Done. Nothing has been committed."
echo "Review with:  git status  &&  git diff --stat"
echo "Then:         git init && git add -A && git commit -m '...' "
echo "              git remote add origin git@github.com:vrishabav/phonetic-speech-memory.git"
echo "              git push -u origin main"
echo "              git rev-parse HEAD      # the SHA the submission form asks for"
