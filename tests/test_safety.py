"""Pruebas de seguridad: ninguna escritura sale si abort / read_only / dry_run / límite."""
import ast
import json
import os

import pytest
import requests

from tests.conftest import FakeResp

# (nombre, argumentos tras ctx, respuesta OK simulada)
WRITES = [
    ("sell_player", (10, 500000), FakeResp(204)),
    ("answer_offer", (77, "accepted"), FakeResp(200)),
    ("create_purchase_offer", (10, 600000), FakeResp(200, {"data": {"id": 5, "status": "waiting"}})),
    ("retract_offer", (77,), FakeResp(204)),
    ("set_lineup", ([1, 2, 3], "4-4-2"), FakeResp(200, {"ok": True})),
]
WRITE_IDS = [w[0] for w in WRITES]


CALLS = []


def _spy_api(*a, **k):
    """Espía: registra la llamada y devuelve éxito (así una fuga sería visible)."""
    CALLS.append(a)
    return FakeResp(204)


@pytest.fixture(autouse=True)
def _reset_calls():
    CALLS.clear()
    yield


# ── 1. Bloqueos: 5 funciones × 4 condiciones = 20 casos ─────────────────────
@pytest.mark.parametrize("name,args,_ok", WRITES, ids=WRITE_IDS)
@pytest.mark.parametrize("flags", [
    {"abort": True},
    {"read_only": True},
    {"dry_run": True},
    {"write_count": 10_000},
], ids=["abort", "read_only", "dry_run", "write_limit"])
def test_escritura_bloqueada(bw, make_ctx, monkeypatch, name, args, _ok, flags):
    monkeypatch.setattr(bw, "api", _spy_api)
    ctx = make_ctx(**flags)
    result = getattr(bw, name)(ctx, *args)
    assert CALLS == [], f"{name} llamó a api() con {flags}"
    assert result[0] is False


# ── 2. Control positivo: sin bloqueos SÍ se escribe (los tests no son vacíos) ─
@pytest.mark.parametrize("name,args,ok", WRITES, ids=WRITE_IDS)
def test_escritura_permitida(bw, make_ctx, monkeypatch, name, args, ok):
    calls = []
    monkeypatch.setattr(bw, "api", lambda *a, **k: calls.append(a) or ok)
    ctx = make_ctx()
    result = getattr(bw, name)(ctx, *args)
    assert result[0] is True
    assert len(calls) == 1 and ctx.write_count == 1


# ── 3. Estructura del código ────────────────────────────────────────────────
def _tree():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "biwenger_daily.py")
    return ast.parse(open(path, encoding="utf-8").read())


def test_guarded_write_definida_una_sola_vez():
    n = [x for x in ast.walk(_tree()) if isinstance(x, ast.FunctionDef) and x.name == "guarded_write"]
    assert len(n) == 1, f"guarded_write definida {len(n)} veces"


def test_guarded_write_comprueba_read_only():
    src = ast.unparse([x for x in ast.walk(_tree())
                       if isinstance(x, ast.FunctionDef) and x.name == "guarded_write"][0])
    for token in ("abort", "read_only", "dry_run", "write_count"):
        assert token in src


def test_ninguna_escritura_fuera_de_guarded_write():
    tree = _tree()
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    offenders = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("api", "_api_write")
                and n.args and isinstance(n.args[0], ast.Constant)
                and str(n.args[0].value).upper() in ("POST", "PUT", "DELETE", "PATCH")):
            cur, ok = n, False
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.Call) and getattr(cur.func, "id", "") == "guarded_write":
                    ok = True
                    break
                if isinstance(cur, ast.FunctionDef) and cur.name == "login":
                    ok = True  # el login no es una escritura de negocio
                    break
            if not ok:
                offenders.append(n.lineno)
    assert not offenders, f"escrituras fuera de guarded_write en líneas {offenders}"


# ── 4. Timeout en escritura → abort + fichero de estado ─────────────────────
class _TimeoutSession:
    def __init__(self):
        self.calls = 0

    def request(self, *a, **k):
        self.calls += 1
        raise requests.exceptions.Timeout("simulado")


def test_timeout_en_post_activa_abort_y_crea_estado(bw, make_ctx, monkeypatch):
    ctx = make_ctx()
    s = _TimeoutSession()
    monkeypatch.setattr(bw, "_SESSION", s, raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    assert not os.path.exists(bw.UNKNOWN_STATE_PATH)
    r = bw.api("POST", "https://biwenger.as.com/api/v2/market", "t", 1, 2, {"player": 1, "price": 5})
    assert r is None
    assert ctx.abort is True
    assert s.calls == 1, "una escritura NO debe reintentarse tras timeout"
    data = json.load(open(bw.UNKNOWN_STATE_PATH))
    assert data and data[0]["method"] == "POST"


def test_tras_abort_no_salen_mas_escrituras(bw, make_ctx, monkeypatch):
    ctx = make_ctx()
    s = _TimeoutSession()
    monkeypatch.setattr(bw, "_SESSION", s, raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    bw.sell_player(ctx, 10, 500000)        # timeout → abort
    assert ctx.abort is True
    before = s.calls
    bw.sell_player(ctx, 11, 500000)
    bw.create_purchase_offer(ctx, 12, 100)
    bw.set_lineup(ctx, [1], "4-4-2")
    assert s.calls == before, "se emitieron peticiones tras el abort"


def test_timeout_en_get_reintenta_y_no_aborta(bw, make_ctx, monkeypatch):
    ctx = make_ctx()
    s = _TimeoutSession()
    monkeypatch.setattr(bw, "_SESSION", s, raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    assert bw.api("GET", "https://biwenger.as.com/api/v2/market", "t", 1, 2) is None
    assert s.calls == bw.MAX_RETRIES + 1
    assert ctx.abort is False
    assert not os.path.exists(bw.UNKNOWN_STATE_PATH)


def test_timeout_en_login_no_crea_estado_ni_aborta(bw, make_ctx, monkeypatch):
    """Un fallo de red en el login no debe dejar el bot bloqueado en modo lectura."""
    ctx = make_ctx()
    monkeypatch.setattr(bw, "_SESSION", _TimeoutSession(), raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    assert bw.api("POST", "https://biwenger.as.com/api/v2/auth/login", body={"email": "x"}) is None
    assert ctx.abort is False
    assert not os.path.exists(bw.UNKNOWN_STATE_PATH)


# ── 5. 429 con Retry-After largo → abort ────────────────────────────────────
class _Session429:
    def __init__(self, retry_after):
        self.retry_after, self.calls = retry_after, 0

    def request(self, *a, **k):
        self.calls += 1
        return FakeResp(429, headers={"Retry-After": str(self.retry_after)})


def test_429_retry_after_largo_aborta(bw, make_ctx, monkeypatch):
    ctx = make_ctx()
    monkeypatch.setattr(bw, "_SESSION", _Session429(120), raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    assert bw.api("GET", "https://biwenger.as.com/api/v2/market", "t", 1, 2) is None
    assert ctx.abort is True


def test_429_en_mitad_de_stage_sell_bench_no_emite_mas_escrituras(bw, make_ctx, monkeypatch):
    """Simula la secuencia: 1ª escritura recibe 429 largo → abort → resto bloqueado."""
    ctx = make_ctx()
    s = _Session429(120)
    monkeypatch.setattr(bw, "_SESSION", s, raising=False)
    monkeypatch.setattr(bw, "_CTX", ctx)
    bw.sell_player(ctx, 10, 500000)
    assert ctx.abort is True
    n = s.calls
    for pid in (11, 12, 13):
        bw.sell_player(ctx, pid, 500000)
    assert s.calls == n


# ── 6. run(): modo lectura, dry-run por defecto y --live ────────────────────
@pytest.fixture
def run_env(bw, monkeypatch):
    """Ejecuta run() hasta justo después de crear ctx, sin red."""
    captured = {}
    real_ctx = bw.Ctx

    class CapCtx(real_ctx):
        def __init__(self):
            super().__init__()
            captured["ctx"] = self

    monkeypatch.setattr(bw, "Ctx", CapCtx)
    monkeypatch.setattr(bw, "TOKEN", "tok")
    monkeypatch.setattr(bw, "get_account", lambda t: (1, 2, 1000, 0, "u"))
    monkeypatch.setattr(bw, "get_squad", lambda c: (None, None, None))  # corta la ejecución
    monkeypatch.setattr(bw, "api", _spy_api)
    return captured


def test_run_sin_live_es_dry_run_aunque_el_entorno_diga_lo_contrario(bw, run_env, monkeypatch):
    monkeypatch.setattr(bw, "DRY_RUN", False)  # simula BIWENGER_DRY_RUN=false
    assert bw.run(live=False) == 1
    assert run_env["ctx"].dry_run is True


def test_run_con_live_permite_escribir(bw, run_env):
    assert bw.run(live=True) == 1
    assert run_env["ctx"].dry_run is False


def test_run_con_unknown_state_entra_en_solo_lectura_y_no_escribe(bw, run_env, monkeypatch):
    with open(bw.UNKNOWN_STATE_PATH, "w") as f:
        json.dump([{"type": "unknown", "method": "POST"}], f)
    bw.run(live=True)
    ctx = run_env["ctx"]
    assert ctx.read_only is True
    monkeypatch.setattr(bw, "api", _spy_api)
    for name, args, _ in WRITES:
        assert getattr(bw, name)(ctx, *args)[0] is False
    assert CALLS == [], "se emitieron escrituras en modo lectura"


def test_run_registra_el_modo_en_el_log(bw, run_env):
    bw.run(live=False)
    log = json.load(open(bw.LOG_FILE))
    modes = [e for e in log if e["action"] == "run_mode"]
    assert modes and modes[-1]["details"]["mode"] == "DRY-RUN"


def test_lockfile_impide_segunda_instancia(bw):
    fd = bw.acquire_instance_lock()
    assert fd is not None
    try:
        assert bw.acquire_instance_lock() is None
    finally:
        os.close(fd)


# ── 7. CLI ──────────────────────────────────────────────────────────────────
def test_cli_live_y_dry_run_son_incompatibles(bw):
    with pytest.raises(SystemExit) as e:
        bw.main(["--live", "--dry-run"])
    assert e.value.code == 2


@pytest.mark.parametrize("argv,expected", [([], False), (["--dry-run"], False), (["--live"], True)])
def test_cli_pasa_live_a_run(bw, monkeypatch, argv, expected):
    got = {}
    monkeypatch.setattr(bw, "run", lambda probe_only=False, live=False: got.update(live=live) or 0)
    assert bw.main(argv) == 0
    assert got["live"] is expected
