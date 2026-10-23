#!/usr/bin/env bash
set -e
cd /opt/data/biwenger-automation || exit 1
echo "== git"; git status -s; git log --oneline -5
echo "== compila"; python3 -m py_compile biwenger_daily.py && echo OK
echo "== escrituras directas"; 
if grep -nE 'api\(\s*"(POST|PUT|DELETE)"' biwenger_daily.py | grep -v guarded_write; then
  echo "FAIL: escrituras fuera de guarded_write"; exit 1
fi
echo "OK"
echo "== pytest"; /opt/data/.venv_biwenger/bin/python -m unittest discover -s tests -v 2>&1 | tail -20
echo "DONE"