"""Tests para stage_process_own_sale_offers — validación de my_sale_ids y snapshot de estado."""
import pytest
from biwenger.stages import stage_process_own_sale_offers, _log_current_state


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


def test_stage_process_own_sale_offers_filtra_my_sale_ids(capsys, monkeypatch):
    """Solo se procesan ofertas cuyos jugadores están en my_sale_ids; los demás se omiten."""
    ctx = FakeCtx()
    accepted_ids = []

    def fake_answer_offer(ctx, offer_id, status):
        if status == "accepted":
            accepted_ids.append(offer_id)
        return (True, "ok")

    monkeypatch.setattr("biwenger.stages.answer_offer", fake_answer_offer)
    monkeypatch.setattr("biwenger.stages.log_action", lambda *a, **k: None)

    stage_process_own_sale_offers(ctx)

    output = capsys.readouterr().out

    # Las ofertas fuera de my_sale_ids deben omitirse con mensaje
    assert "se omite" in output, "Debería haber mensajes de omisión"
    assert "2303700935" in output, "Oferta por Olasagasti debería estar como omitida"
    assert "3978901749" in output, "Oferta por Gulácsi debería estar como omitida"

    # answer_offer NO debe haberse llamado para ofertas fuera de my_sale_ids
    # (oferta 100 es de tipo "received", no "own_sale", así que no se procesa en este stage)
    assert accepted_ids == [], f"No se debió llamar answer_offer, pero se llamó con: {accepted_ids}"


def test_stage_no_llama_a_answer_offer_para_ofertas_fuera_de_my_sale_ids(monkeypatch):
    """Verificar que answer_offer nunca se llama para ofertas de jugadores no en venta."""
    ctx = FakeCtx()
    calls = []

    def fake_answer_offer(ctx, offer_id, status):
        calls.append((offer_id, status))
        return (True, "ok")

    monkeypatch.setattr("biwenger.stages.answer_offer", fake_answer_offer)
    monkeypatch.setattr("biwenger.stages.log_action", lambda *a, **k: None)

    stage_process_own_sale_offers(ctx)

    # No debe haber llamadas a answer_offer porque las ofertas válidas
    # (100) son del tipo "received" (from.id=None), no "own_sale" (from.id=user_id)
    assert calls == [], f"Se llamò answer_offer incorrectamente: {calls}"
