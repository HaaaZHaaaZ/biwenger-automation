#!/usr/bin/env bash
set -e
cd /opt/data/biwenger-automation || exit 1
echo "== git status"; git status -s
echo "== git log"; git log --oneline -5
echo "== compila"; python3 -m py_compile biwenger_daily.py && echo OK
echo "== escrituras directas";
BAD=$(grep -nE 'api\(\s*"(POST|PUT|DELETE)"' biwenger_daily.py | grep -v guarded_write || true)
if [ -n "$BAD" ]; then
  echo "FAIL: escrituras fuera de guarded_write:"
  echo "$BAD"
  exit 1
fi
echo "OK"
echo "== pytest"; /opt/data/.venv_biwenger/bin/python -m pytest -v
echo "ALL DONE"