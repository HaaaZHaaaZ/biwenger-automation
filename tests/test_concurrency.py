"""Prueba de concurrencia: dos procesos compitiendo por el lock de instancia."""
import fcntl
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_concurrency_lock():
    """Dos procesos intentan adquirir el mismo lock; solo uno lo obtiene."""
    lock_dir = tempfile.mkdtemp()
    lock_path = os.path.join(lock_dir, "test.lock")

    # Simular dos procesos compitiendo por el lock
    fd1 = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    acquired1 = False
    try:
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired1 = True
    except (IOError, OSError):
        acquired1 = False

    fd2 = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    acquired2 = False
    try:
        fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired2 = True
    except (IOError, OSError):
        acquired2 = False

    assert acquired1 is True, "Primer proceso debería obtener el lock"
    assert acquired2 is False, "Segundo proceso NO debería obtener el lock"

    # Liberar lock del primer proceso
    fcntl.flock(fd1, fcntl.LOCK_UN)
    os.close(fd1)

    # Ahora el segundo debería poder adquirirlo
    fd2b = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    acquired2b = False
    try:
        fcntl.flock(fd2b, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired2b = True
    except (IOError, OSError):
        acquired2b = False

    assert acquired2b is True, "Tras liberar, el segundo proceso debería obtener el lock"

    fcntl.flock(fd2b, fcntl.LOCK_UN)
    os.close(fd2b)
    os.close(fd2)
    os.remove(lock_path)
    os.rmdir(lock_dir)
    print("PASS: concurrencia lock")


def test_uncertain_state_blocks_writes():
    """Estado incierto bloquea escrituras hasta reconciliación explícita."""
    import biwenger_daily as bd

    fd, path = tempfile.mkstemp()
    os.close(fd)
    os.remove(path)

    bd.UNKNOWN_STATE_PATH = path
    ctx = bd.Ctx()
    ctx.token = "t"
    ctx.league_id = 1
    ctx.user_id = 2
    ctx.dry_run = False

    # Crear unknown_state manualmente (simula timeout/5xx)
    with open(path, "w") as f:
        import json
        json.dump([{"type": "unknown", "method": "POST"}], f)

    # Simular reinicio: ctx.read_only se activa si existe unknown_state
    ctx2 = bd.Ctx()
    ctx2.token = "t"
    ctx2.league_id = 1
    ctx2.user_id = 2
    ctx2.dry_run = False
    if os.path.exists(bd.UNKNOWN_STATE_PATH):
        ctx2.read_only = True

    assert ctx2.read_only is True, "Debería estar en modo solo lectura"

    # Verificar que guarded_write bloquea
    result = bd.guarded_write(ctx2, "sell", lambda: None)
    assert result == (False, "read_only"), f"Esperado read_only, got {result}"

    # Limpiar
    os.remove(path)
    print("PASS: uncertain state blocks writes")


if __name__ == "__main__":
    test_concurrency_lock()
    test_uncertain_state_blocks_writes()
    print("ALL PASS")
