"""Tests del snapshot de estado de las etapas."""
import pytest
from biwenger.stages import _log_current_state


class FakeCtx:
    """Contexto simulado para pruebas."""
    def __init__(self):
        self.abort = False
        self.user_id = 13947894
        self.my_sale_ids = {37894}  # Pablo Campos (única venta activa)
        self.opt_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        self.squad_ids = list(range(1, 15))
        self.catalog = {
            "37894": {"name": "Pablo Campos", "price": 440000, "status": "ok", "position": 1},
            "29661": {"name": "Olasagasti", "price": 2990000, "status": "ok", "position": 3},
            "38433": {"name": "Gulácsi", "price": 2589601, "status": "ok", "position": 1},
            "14492359": {"name": "Sergi Cardona", "price": 1551000, "status": "ok", "position": 2},
        }
        self.pool = {pid: {"name": f"Player{pid}", "score": 2.0, "position": 2}
                     for pid in range(1, 15)}
        self.offers = [
            # Oferta válida: por Pablo Campos (en my_sale_ids)
            {"id": 100, "status": "waiting", "amount": 500000,
             "from": {"id": None}, "to": {"id": 13947894},
             "requestedPlayers": [{"id": 37894}]},
            # Oferta inválida: por Olasagasti (NO en my_sale_ids)
            {"id": 2303700935, "status": "waiting", "amount": 3109601,
             "from": {"id": 13947894}, "to": {"id": 999},
             "requestedPlayers": [{"id": 29661}]},
            # Oferta inválida: por Gulácsi (NO en my_sale_ids)
            {"id": 3978901749, "status": "waiting", "amount": 2589601,
             "from": {"id": 13947894}, "to": {"id": 998},
             "requestedPlayers": [{"id": 38433}]},
        ]
        self.write_count = 0
        self.balance = 8000000
        self.captain_called = False
        self.striker_called = False

    def can_write(self):
        return True

    def recompute(self):
        pass

    def act(self, action, **kwargs):
        pass


def test_log_current_state_imprime_sin_explotar(capsys):
    """_log_current_state no debe levantar excepción."""
    ctx = FakeCtx()
    _log_current_state(ctx, "test_snapshot")
    captured = capsys.readouterr()
    assert "test_snapshot" in captured.out
    assert "Alineación óptima" in captured.out
    assert "Ventas activas" in captured.out
