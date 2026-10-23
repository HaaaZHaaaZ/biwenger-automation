#!/usr/bin/env bash
# Control de calidad: falla (exit != 0) si algo está mal. Uso: ./verify.sh
cd "$(dirname "$0")" || exit 1
FAIL=0
step() { echo; echo "== $1"; }

step "git"
git status -s 2>/dev/null || echo "(no es un repo git)"
git log --oneline -5 2>/dev/null

step "compila"
python3 -m py_compile biwenger_daily.py && echo OK || { echo FALLA; FAIL=1; }

step "nombres indefinidos / redefiniciones (pyflakes)"
OUT=$(python3 -m pyflakes biwenger_daily.py 2>&1 | grep -E "undefined name|redefinition of unused")
if [ -n "$OUT" ]; then echo "$OUT"; FAIL=1; else echo OK; fi

step "escrituras api(POST|PUT|DELETE) (todas deben estar dentro de guarded_write)"
grep -nE 'api\(\s*"(POST|PUT|DELETE)"' biwenger_daily.py
echo "(la comprobación estricta la hace tests/test_safety.py::test_ninguna_escritura_fuera_de_guarded_write)"

step "guarded_write definidas"
N=$(grep -c "^def guarded_write" biwenger_daily.py); echo "$N"
[ "$N" = "1" ] || { echo "FALLA: debe haber exactamente 1"; FAIL=1; }

step "pytest"
/opt/data/.venv_biwenger/bin/python -m pytest -v || FAIL=1

echo
if [ "$FAIL" = "0" ]; then echo "RESULTADO: OK (exit=0)"; else echo "RESULTADO: FALLA (exit=1)"; fi
exit $FAIL
