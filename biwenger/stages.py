"""Biwenger stages — todas las etapas del flujo de ejecución."""
import time

from biwenger import config as cfg
from biwenger import model
from biwenger.utils import log_action
from biwenger.writes import sell_player, answer_offer, create_purchase_offer, set_lineup, retract_offer
from biwenger.scoring import (
    choose_captain_and_striker,
    offer_player_ids, lineup_is_complete,
    build_free_market
)
from biwenger.config import (
    BAD_STATUS, POS_NAMES, MIN_P_START_BUY, MATCH_SOON_HOURS,
    SELL_BENCH_WHEN_LINEUP_READY, MIN_LINEUP_GAIN, MIN_BUY_GAIN,
    BID_LOW, BID_MID, BID_HIGH, MAX_BID_PCT, BID_PLUS_ONE,
    CAPTAIN_MAX_VALUE, CAPTAIN_KEY, STRIKER_KEY,
    ACCEPT_NORMAL, ACCEPT_HIGH, ACCEPT_INJURED, MAX_DROP_PCT,
    ACCEPT_MACHINE_MIN, MAX_TEAM_SIZE, SELL_SCORE_MIN
)


# Escrituras reservadas a la alineación: es lo último que se envía y lo único que da puntos.
LINEUP_RESERVE = 1
HOLD_SECONDS = 24 * 3600   # "Debes esperar 1 día para poder vender o comprar a..."


def _held_too_recently(ctx, pid):
    """Recién comprado: la API rechaza la venta con 403 y se gastaría una escritura."""
    owned_since = (getattr(ctx, "owner_info", {}).get(pid) or {}).get("date")
    return bool(owned_since) and time.time() - owned_since < HOLD_SECONDS


def _sales_slots(ctx):
    """Huecos de venta según el límite de la liga (marketMaxUserSales). None = sin límite."""
    limit = getattr(ctx, "max_user_sales", 0)
    return None if not limit else max(limit - len(ctx.my_sale_ids), 0)


def _is_surplus(ctx, e):
    """Suplente prescindible: su valor de fondo no llega al del peor titular.
    Un suplente mejor que eso (p. ej. un titular con una duda puntual) se conserva."""
    detail = ctx.opt_detail or {}
    starters = [x for k in ("gk", "def", "mid", "fwd") for x in detail.get(k, [])]
    if not starters:
        return False
    return e.get("value", e["score"]) < min(x.get("slot_score", x["score"]) for x in starters)


def _is_last_backup_gk(ctx, e):
    """Con un solo portero disponible, una baja dejaría el once sin hueco cubierto."""
    if e["position"] != 1:
        return False
    keepers = sum(1 for x in ctx.pool.values() if x["position"] == 1 and x["id"] not in ctx.my_sale_ids)
    return keepers <= 2


def _lineup_lines(ids, formation):
    """Separa una alineación en líneas según la formación: el orden dentro de cada línea da igual."""
    try:
        nd, nm, nf = (int(n) for n in (formation or "").split("-"))
    except ValueError:
        return None
    if len(ids) != 1 + nd + nm + nf:
        return None
    return [set(ids[:1]), set(ids[1:1 + nd]), set(ids[1 + nd:1 + nd + nm]), set(ids[1 + nd + nm:])]


def _log_current_state(ctx, stage_name: str):
    """Snapshot de estado para auditoría antes de procesar ofertas."""
    print(f"\n  📋 Estado actual [{stage_name}]:")
    # Alineación óptima
    opt_names = [ctx.pool[pid]['name'] for pid in ctx.opt_ids if pid in ctx.pool]
    print(f"     Alineación óptima ({len(ctx.opt_ids)}): {opt_names}")
    # Ventas activas
    sale_names = [ctx.catalog.get(str(pid), {}).get('name', f'id={pid}') for pid in ctx.my_sale_ids]
    print(f"     Ventas activas ({len(ctx.my_sale_ids)}): {sale_names}")
    # Pujas propias pendientes (compra)
    own_buy_offers = [o for o in ctx.offers
                      if o.get("status") == "waiting"
                      and (o.get("to") or {}).get("id") is None
                      and (o.get("from") or {}).get("id") == ctx.user_id]
    own_buy_desc = []
    for o in own_buy_offers:
        pids = offer_player_ids(o)
        if pids:
            pid = pids[0]
            name = ctx.catalog.get(str(pid), {}).get('name', '?')
            own_buy_desc.append(f"{name} €{o.get('amount', 0):,}")
    print(f"     Pujas propias pendientes ({len(own_buy_offers)}): {own_buy_desc}")
    # Ofertas recibidas (otros usuarios ofertando por nuestros jugadores)
    received_offers = [o for o in ctx.offers
                       if o.get("status") == "waiting"
                       and (o.get("to") or {}).get("id") == ctx.user_id
                       and (o.get("from") or {}).get("id") is None]
    received_desc = []
    for o in received_offers:
        pids = offer_player_ids(o)
        if pids:
            pid = pids[0]
            name = ctx.catalog.get(str(pid), {}).get('name', '?')
            received_desc.append(f"{name} €{o.get('amount', 0):,}")
    print(f"     Ofertas recibidas ({len(received_offers)}): {received_desc}")
    # Ofertas en nuestras ventas (compradores ofertando por lo que vendemos)
    own_sale_offers = [o for o in ctx.offers
                       if o.get("status") == "waiting"
                       and (o.get("from") or {}).get("id") == ctx.user_id
                       and (o.get("to") or {}).get("id") != ctx.user_id]
    own_sale_desc = []
    for o in own_sale_offers:
        pids = offer_player_ids(o)
        if pids:
            pid = pids[0]
            name = ctx.catalog.get(str(pid), {}).get('name', '?')
            own_sale_desc.append(f"{name} €{o.get('amount', 0):,}")
    print(f"     Ofertas en nuestras ventas ({len(own_sale_offers)}): {own_sale_desc}")


def stage_cleanup_offers(ctx):
    if getattr(ctx, "abort", False):
        return
    """Retira ofertas propias de jugadores no disponibles y las que sobrepasan el saldo."""
    own = [o for o in ctx.offers
           if o.get("status") == "waiting" and (o.get("from") or {}).get("id") == ctx.user_id]
    ctx.pending_ids = {pid for o in own for pid in offer_player_ids(o)}
    scores = {r["id"]: r["score"] for r in ctx.free_market}
    keep = []
    for o in own:
        pids = offer_player_ids(o)
        pid = pids[0] if pids else None
        cp = ctx.catalog.get(str(pid)) if pid else None
        st = ((cp or {}).get("status") or "ok").lower()
        if st in BAD_STATUS and ctx.can_write(LINEUP_RESERVE):
            ok, msg = retract_offer(ctx, o.get("id"))
            print(f"  ↩️ Retiro oferta #{o.get('id')} por {(cp or {}).get('name', pid)} ({st}): {msg}")
            if ok:
                ctx.pending_ids.discard(pid)
                ctx.act("offer_retracted", offer_id=o.get("id"), player_id=pid, reason=st)
                log_action("offer_retracted", {"offer_id": o.get("id"), "player_id": pid, "reason": st}, "success")
                continue
        keep.append(o)

    committed = sum(o.get("amount", 0) or 0 for o in keep)
    limit = ctx.balance - ctx.cushion()
    if committed > limit:
        keep.sort(key=lambda o: scores.get((offer_player_ids(o) or [0])[0], 0))
        while keep and committed > limit and ctx.can_write(LINEUP_RESERVE):
            o = keep[0]
            ok, msg = retract_offer(ctx, o.get("id"))
            if not ok:
                break
            keep.pop(0)
            committed -= o.get("amount", 0) or 0
            for pid in offer_player_ids(o):
                ctx.pending_ids.discard(pid)
            print(f"  ↩️ Retiro oferta #{o.get('id')}: comprometido por encima del saldo disponible")
            ctx.act("offer_retracted", offer_id=o.get("id"), reason="over_committed")
            log_action("offer_retracted", {"offer_id": o.get("id"), "reason": "over_committed"}, "success")
    ctx.committed = committed


def stage_received_offers(ctx):
    if getattr(ctx, "abort", False):
        return
    """Acepta/rechaza ofertas recibidas simulando antes la plantilla resultante."""
    _log_current_state(ctx, "ofertas_recibidas")
    print("\n  0. Ofertas recibidas:")
    received = [o for o in ctx.offers
                if o.get("status") == "waiting"
                and (o.get("to") or {}).get("id") == ctx.user_id
                and (o.get("from") or {}).get("id") != ctx.user_id]
    if not received:
        print("     ✅ No hay ofertas recibidas")
        return
    sold = set()
    # La mejor oferta primero: antes se aceptaba la primera válida aunque hubiera otra mayor.
    for o in sorted(received, key=lambda x: x.get("amount", 0) or 0, reverse=True):
        if not ctx.can_write(LINEUP_RESERVE):
            print("     ⚠️ Límite de escrituras alcanzado")
            break
        oid, amount = o.get("id"), o.get("amount", 0) or 0
        pids = offer_player_ids(o)
        otype = (o.get("type") or "purchase").lower()
        if len(pids) != 1 or otype != "purchase" or o.get("offeredPlayers"):
            log_action("offer_skipped_complex", {"offer_id": oid, "type": otype, "players": pids}, "info")
            print(f"     ⏸ Oferta #{oid} compleja (tipo={otype}, jugadores={len(pids)}) — no se toca")
            continue
        pid = pids[0]
        if pid in sold:
            continue
        cp = ctx.catalog.get(str(pid))
        if not cp:
            print(f"     ⚠️ Oferta #{oid}: jugador id={pid} no está en el catálogo")
            continue
        name = cp.get("name", f"id={pid}")
        market_price = cp.get("price", 0) or 0
        if market_price <= 0:
            print(f"     ⚠️ Oferta #{oid} por {name}: sin precio de mercado, no se evalúa")
            continue
        ratio = amount / market_price
        st = (cp.get("status") or "ok").lower()
        injured = st in BAD_STATUS
        who = "📱 Computer" if abs(ratio - 1) <= 0.05 and (o.get("from") or {}).get("id") is None else "👤 Usuario"
        print(f"     {who} #{oid} por {name} — €{amount:,} (ratio={ratio*100:.1f}%)")

        # Simulación: plantilla sin ese jugador
        after = [i for i in ctx.squad_ids if i != pid]
        ids_a, _, detail_a, _ = ctx.simulate(after)
        valid_after = ids_a is not None and len(ids_a) == 11
        total_b = ctx.opt_detail["total"] if ctx.opt_detail else 0.0
        total_a = detail_a["total"] if detail_a else 0.0
        drop = (total_b - total_a) / total_b if total_b > 0 else 0.0
        entry = ctx.pool.get(pid) or {"score": 0, "position": cp.get("position", 0)}
        replacement_market = any(
            r["position"] == entry["position"] and r["status"] == "ok"
            and r["score"] >= entry["score"] and r["p_start"] >= MIN_P_START_BUY
            for r in ctx.free_market)
        has_replacement = (valid_after and drop <= MAX_DROP_PCT) or (valid_after and replacement_market)

        # Valor de fondo: una duda puntual no convierte en vendible a un buen jugador.
        value = entry.get("value", entry.get("score", 99))
        bench_on_sale = pid in ctx.my_sale_ids and pid not in ctx.opt_ids
        surplus = bench_on_sale and pid in ctx.pool and _is_surplus(ctx, ctx.pool[pid])
        accept, reason = False, ""
        if not valid_after:
            reason = "dejaría posiciones sin cubrir"
        elif ctx.balance < 0 and pid not in ctx.opt_ids and ratio >= ACCEPT_INJURED:
            # Con saldo negativo al empezar la jornada se puntúa 0: prima volver a positivo.
            accept, reason = True, f"saldo negativo ({ctx.balance:,}) y oferta ≥ {ACCEPT_INJURED*100:.0f}%"
        elif ratio >= ACCEPT_HIGH:
            accept, reason = True, f"oferta ≥ {ACCEPT_HIGH*100:.0f}% del mercado"
        elif ratio >= ACCEPT_NORMAL and has_replacement:
            accept, reason = True, f"oferta ≥ {ACCEPT_NORMAL*100:.0f}% y hay reemplazo (caída {drop*100:.1f}%)"
        elif injured and ratio >= ACCEPT_INJURED:
            accept, reason = True, f"{st} y oferta ≥ {ACCEPT_INJURED*100:.0f}%"
        elif ratio >= ACCEPT_MACHINE_MIN and bench_on_sale and (value < SELL_SCORE_MIN or surplus):
            # Desbloqueo de cupo: suplente ya en venta y prescindible. Completar la venta
            # libera un hueco de plantilla y da caja.
            accept, reason = True, (f"desbloqueo de cupo: en venta, valor {value:.2f} "
                                    f"y oferta ≥ {ACCEPT_MACHINE_MIN*100:.0f}% del mercado")
        else:
            applicable = ACCEPT_INJURED if injured else (ACCEPT_NORMAL if has_replacement else ACCEPT_MACHINE_MIN)
            reason = (f"ratio {ratio*100:.1f}% insuficiente (mínimo aplicable {applicable*100:.0f}%) "
                      f"o sin reemplazo")

        if accept:
            ok, msg = answer_offer(ctx, oid, "accepted")
            if ok:
                print(f"       ✅ Aceptada — {reason}")
                ctx.act("offer_accepted", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_accepted", {"offer_id": oid, "player_id": pid, "player_name": name,
                                              "amount": amount, "reason": reason}, "success")
                sold.add(pid)
                ctx.squad_ids = after
                ctx.my_sale_ids.discard(pid)
                ctx.balance += amount
                ctx.recompute()
            else:
                print(f"       ❌ Error aceptando: {msg}")
                log_action("offer_accept_failed", {"offer_id": oid, "reason": msg}, "error")
        else:
            ok, msg = answer_offer(ctx, oid, "rejected")
            if ok:
                print(f"       ❌ Rechazada — {reason}")
                ctx.act("offer_rejected", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_rejected", {"offer_id": oid, "player_id": pid, "player_name": name,
                                              "amount": amount, "reason": reason}, "success")
            else:
                print(f"       ❌ Error rechazando: {msg}")
                log_action("offer_reject_failed", {"offer_id": oid, "reason": msg}, "error")


def stage_process_own_sale_offers(ctx):
    """OBSOLETA, fuera del flujo de run(): filtra from=nosotros, es decir, nuestras propias
    pujas, nunca ofertas de compradores. Esas llegan con to=nosotros y las atiende
    stage_received_offers."""
    _log_current_state(ctx, "ofertas_ventas_propias")
    print("\n  0b. Ofertas en nuestras ventas:")
    if getattr(ctx, "abort", False):
        return
    # Ofertas donde somos el vendedor (from.id == ctx.user_id) y el jugador está en venta
    own_sale_offers = [o for o in ctx.offers
                       if o.get("status") == "waiting"
                       and (o.get("from") or {}).get("id") == ctx.user_id
                       and (o.get("to") or {}).get("id") != ctx.user_id]

    if not own_sale_offers:
        print("     ✅ No hay ofertas en nuestras ventas")
        return

    for o in own_sale_offers:
        if not ctx.can_write():
            print("     ⚠️ Límite de escrituras alcanzado")
            break
        oid, amount = o.get("id"), o.get("amount", 0) or 0
        pids = offer_player_ids(o)
        if len(pids) != 1:
            continue
        pid = pids[0]
        # FIX: Solo procesar ofertas sobre jugadores que tenemos EN VENTA ACTIVA
        if pid not in ctx.my_sale_ids:
            cp = ctx.catalog.get(str(pid))
            name = cp.get("name", f"id={pid}") if cp else f"id={pid}"
            print(f"     ⏭️  Oferta #{oid} por {name} (id={pid}) — no está en nuestras ventas activas, se omite")
            continue
        cp = ctx.catalog.get(str(pid))
        if not cp:
            continue
        name = cp.get("name", f"id={pid}")
        market_price = cp.get("price", 0) or 0
        ratio = amount / market_price if market_price > 0 else 0

        print(f"     📥 Oferta #{oid} por {name} — €{amount:,} (ratio={ratio*100:.1f}%)")

        # Aceptar si ratio >= ACCEPT_NORMAL (1.10) o si está lesionado y ratio >= ACCEPT_INJURED (0.90)
        st = (cp.get("status") or "ok").lower()
        injured = st in BAD_STATUS
        accept = False
        reason = ""

        if ratio >= ACCEPT_HIGH:
            accept, reason = True, f"oferta ≥ {ACCEPT_HIGH*100:.0f}% del mercado"
        elif ratio >= ACCEPT_NORMAL:
            accept, reason = True, f"oferta ≥ {ACCEPT_NORMAL*100:.0f}% del mercado"
        elif injured and ratio >= ACCEPT_INJURED:
            accept, reason = True, f"{st} y oferta ≥ {ACCEPT_INJURED*100:.0f}%"
        else:
            reason = f"ratio {ratio*100:.1f}% insuficiente"

        if accept:
            ok, msg = answer_offer(ctx, oid, "accepted")
            if ok:
                print(f"       ✅ Aceptada — {reason}")
                ctx.balance += amount
                ctx.act("offer_accepted", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_accepted", {"offer_id": oid, "player_id": pid, "player_name": name, "amount": amount, "reason": reason}, "success")
                # Remove from our sale list
                ctx.my_sale_ids.discard(pid)
                ctx.squad_ids = [i for i in ctx.squad_ids if i != pid]
                ctx.recompute()
            else:
                print(f"       ❌ Error aceptando: {msg}")
        else:
            ok, msg = answer_offer(ctx, oid, "rejected")
            if ok:
                print(f"       ❌ Rechazada — {reason}")
                ctx.act("offer_rejected", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_rejected", {"offer_id": oid, "player_id": pid, "player_name": name, "amount": amount, "reason": reason}, "success")
            else:
                print(f"       ❌ Error rechazando: {msg}")


def stage_sell_bench(ctx):
    if getattr(ctx, "abort", False):
        return
    """Vende suplentes lesionados o de valor bajo solo si conviene."""
    print("\n  1. Ventas de suplentes:")
    starters = set(ctx.opt_ids)
    sold = simulated = 0
    slots = _sales_slots(ctx)
    # Los que ya están en venta también saldrán: cuentan para el mínimo de plantilla.
    on_sale = len(ctx.my_sale_ids)
    for e in sorted(ctx.pool.values(), key=lambda x: x.get("value", x["score"])):
        if e["id"] in starters or e["id"] in ctx.my_sale_ids:
            continue
        if sold >= cfg.MAX_SELLS or not ctx.can_write(LINEUP_RESERVE):
            break
        if slots is not None and sold >= slots:
            print(f"     ⏸ Límite de ventas simultáneas de la liga ({ctx.max_user_sales})")
            break
        if len(ctx.squad_ids) - on_sale - sold <= cfg.MIN_SQUAD:
            print(f"     ⏸ Plantilla mínima ({cfg.MIN_SQUAD}) — no se vende más")
            break
        st = (e.get("status") or "ok").lower()
        # La decisión usa el valor de fondo, no la puntuación de esta jornada: la del
        # 01/11 puso a la venta a Lemar (5,19 M€) por una duda (score 3,36 × 0,55).
        value = e.get("value", e["score"])
        bad, low = st in BAD_STATUS, value < SELL_SCORE_MIN
        if not (bad or low):
            continue
        if _is_last_backup_gk(ctx, e):
            print(f"     ⏸ {e['name']} — portero de reserva, se conserva")
            continue
        if _held_too_recently(ctx, e["id"]):
            print(f"     ⏸ {e['name']} — comprado hace menos de 1 día, aún no se puede vender")
            continue
        lineup_ready = len(ctx.opt_ids) >= 11
        if low and not bad and ctx.match_soon and not (lineup_ready and SELL_BENCH_WHEN_LINEUP_READY):
            print(f"     ⏸ {e['name']} (valor={value:.3f}) — partido cerca y alineación "
                  f"sin cerrar ({len(ctx.opt_ids)}/11), se mantiene")
            continue
        if low and not bad and lineup_ready and SELL_BENCH_WHEN_LINEUP_READY and value < 1.5:
            print(f"     🔓 {e['name']} (valor={value:.3f}) — alineación cerrada, se vende")
            has_repl = True
        else:
            has_repl = any(r["position"] == e["position"] and r["status"] == "ok"
                           and r["score"] > value and r["p_start"] >= MIN_P_START_BUY
                           for r in ctx.free_market)
        if not has_repl:
            print(f"     ⏸ {e['name']} ({st}, valor={value:.3f}) — sin mejor reemplazo en el mercado")
            continue
        price = ctx.catalog.get(str(e["id"]), {}).get("price", 0)
        reason = f"status={st}" if bad else f"valor_bajo={value:.3f}"
        # Sin precio fiable, sell_player rechaza la venta (no_market_price).
        ok, msg, used = sell_player(ctx, e["id"], price)
        if ok:
            print(f"     ✅ {e['name']} en venta a €{used:,} ({reason})")
            sold += 1
            ctx.my_sale_ids.add(e["id"])
            ctx.act("sell_sub", player_id=e["id"], player_name=e["name"], price=used)
            log_action("sell_sub", {"player_id": e["id"], "player_name": e["name"],
                                    "reason": reason, "price": used}, "success")
        elif msg == "dry_run":
            simulated += 1
            print(f"     🧪 Simulado: {e['name']} en venta a €{used:,} ({reason})")
        else:
            print(f"     ❌ {e['name']}: {msg}")
            ctx.act("sell_sub_failed", player_id=e["id"], player_name=e["name"], reason=msg)
            log_action("sell_sub_failed", {"player_id": e["id"], "player_name": e["name"], "reason": msg}, "error")
    if sold == 0 and simulated == 0:
        print("     ✅ Nada que vender ahora")


def _free_slot_for_upgrade(ctx, best):
    """Plantilla llena y un fichaje que mejora el once: pone a la venta al suplente menos útil.

    Antes el bot se bloqueaba en 16/16: sin ventas no había cupo, y sin suplente de
    score bajo no había ventas. Se lista uno a la vez y nunca a un titular.
    """
    if any(_is_surplus(ctx, ctx.pool[i]) for i in ctx.my_sale_ids if i in ctx.pool and i not in ctx.opt_ids):
        print("     ⏸ Ya hay un suplente prescindible en venta: se espera a que libere el cupo")
        return
    if not ctx.can_write(LINEUP_RESERVE) or _sales_slots(ctx) == 0:
        return
    if len(ctx.squad_ids) <= cfg.MIN_SQUAD:
        return
    bench = [e for e in ctx.pool.values()
             if e["id"] not in ctx.opt_ids and e["id"] not in ctx.my_sale_ids
             and not _held_too_recently(ctx, e["id"]) and not _is_last_backup_gk(ctx, e)]
    if not bench:
        print("     ⏸ Ningún suplente se puede vender ahora mismo")
        return
    out = min(bench, key=lambda e: e.get("value", e["score"]))
    price = ctx.catalog.get(str(out["id"]), {}).get("price", 0)
    ok, msg, used = sell_player(ctx, out["id"], price)
    label = f"{out['name']} (valor {out.get('value', out['score']):.2f}) para fichar a {best['name']} (+{best['gain']:.2f} pts/jornada)"
    if ok:
        print(f"     🔁 En venta {label}")
        ctx.my_sale_ids.add(out["id"])
        ctx.act("sell_sub", player_id=out["id"], player_name=out["name"], price=used)
        log_action("sell_for_upgrade", {"player_id": out["id"], "player_name": out["name"], "price": used,
                                        "target": best["name"], "gain": best["gain"]}, "success")
    elif msg == "dry_run":
        print(f"     🧪 Simulado: en venta {label}")
    else:
        print(f"     ❌ {out['name']}: {msg}")
        ctx.act("sell_sub_failed", player_id=out["id"], player_name=out["name"], reason=msg)
        log_action("sell_sub_failed", {"player_id": out["id"], "player_name": out["name"], "reason": msg}, "error")


def stage_buy(ctx):
    if getattr(ctx, "abort", False):
        return
    """Pujas por jugadores del mercado libre según lo que mejoran el once en puntos esperados."""
    print("\n  2. Compras:")
    if ctx.balance < 0:
        print("     🚨 Saldo negativo: no se compra (empezar la jornada en negativo son 0 puntos)")
        log_action("balance_negative", {"balance": ctx.balance}, "warning")
        return
    if cfg.MAX_SQUAD and len(ctx.squad_ids) >= cfg.MAX_SQUAD:
        print(f"     ⏸ Plantilla completa ({cfg.MAX_SQUAD})")
        return

    cands = [r for r in ctx.free_market if r["status"] == "ok" and r["id"] not in ctx.pending_ids
             and r["id"] not in ctx.squad_ids and r["p_start"] >= MIN_P_START_BUY]
    cands.sort(key=lambda r: r["score"], reverse=True)
    print(f"     Mercado libre evaluado: {len(ctx.free_market)} · candidatos: {len(cands)}")
    for r in cands[:5]:
        print(f"       {r['name']:22} {POS_NAMES.get(r['position'], '?'):3} score={r['score']:6.3f} €{r['price']:,}")

    # Mejora real del once con la formación y la multiposición recalculadas: comparar
    # solo con el peor titular de su línea ignoraba los cambios de formación.
    current = ctx.opt_detail["total"] if ctx.opt_detail else 0.0
    upgrades = []
    for r in cands:
        if r["price"] > ctx.balance:
            continue
        _, _, detail, _ = ctx.simulate(list(ctx.squad_ids) + [r["id"]])
        gain = round((detail["total"] if detail else 0.0) - current, 3)
        if gain >= MIN_BUY_GAIN:
            upgrades.append({**r, "gain": gain})
    upgrades.sort(key=lambda r: r["gain"], reverse=True)

    # El cupo de la liga cuenta jugadores + ofertas abiertas. Al máximo, la API responde
    # 403 "Maximum team size reached".
    own_open = {pid for o in ctx.offers
                if o.get("status") == "waiting" and (o.get("from") or {}).get("id") == ctx.user_id
                for pid in offer_player_ids(o)}
    occupied = len(ctx.squad_ids) + len(own_open)
    team_max = getattr(ctx, "team_max", MAX_TEAM_SIZE)
    if occupied >= team_max:
        on_sale = len(ctx.my_sale_ids)
        print(f"     ⏸ Cupo de liga completo ({occupied}/{team_max}): "
              f"{len(ctx.squad_ids)} jugadores ({len(ctx.squad_ids)-on_sale} libres + "
              f"{on_sale} en venta) + {len(own_open)} ofertas abiertas")
        log_action("buy_check", {"result": "team_full", "occupied": occupied,
                                 "max": team_max, "on_sale": on_sale,
                                 "upgrades": len(upgrades)}, "info")
        if upgrades:
            print(f"     Mejor fichaje posible: {upgrades[0]['name']} (+{upgrades[0]['gain']:.2f} pts/jornada)")
            _free_slot_for_upgrade(ctx, upgrades[0])
        return

    if not upgrades:
        print("     ✅ Ningún jugador del mercado mejora el once lo suficiente")
        log_action("buy_check", {"result": "no_upgrade_available", "evaluados": len(cands)}, "info")
        return

    available = ctx.balance - ctx.committed - ctx.cushion()
    maximum_bid = getattr(ctx, "maximum_bid", 0)
    print(f"     💰 Saldo €{ctx.balance:,} · comprometido €{ctx.committed:,} · "
          f"colchón €{ctx.cushion():,.0f} · disponible €{available:,.0f}")

    bought, bought_pos = 0, set()
    for p in upgrades:
        if bought >= cfg.MAX_BUYS or not ctx.can_write(LINEUP_RESERVE):
            break
        if occupied + bought >= team_max:
            print(f"     ⏸ Cupo de liga completo con esta puja ({team_max})")
            break
        if p["position"] in bought_pos:
            continue
        pid, price = p["id"], p["price"]
        trend = (ctx.catalog.get(str(pid)) or {}).get("priceIncrement") or 0
        if p["score"] > 5.0 and price > 3_000_000:
            competition = "alta"
        elif p["score"] > 3.5 or (trend > 0 and p["score"] > 3.0):
            competition = "media"
        else:
            competition = "baja"
        mult = {"baja": BID_LOW, "media": BID_MID, "alta": BID_HIGH}[competition]
        max_bid = int(price * MAX_BID_PCT)
        bid = min(int(price * mult), max_bid)
        if BID_PLUS_ONE:
            bid = min(bid + 1, max_bid + 1)
        if not getattr(ctx, "bids_over_mv", True):
            bid = price      # la liga no admite pujas sobre el valor de mercado
        if maximum_bid:
            bid = min(bid, maximum_bid)
        print(f"     → {p['name']} ({POS_NAMES.get(p['position'], '?')}) mercado €{price:,} · "
              f"score {p['score']} · mejora el once +{p['gain']:.2f} · "
              f"competencia {competition} · puja €{bid:,}")
        if bid > available:
            print(f"       ⚠️ Excede el saldo disponible — se omite")
            continue
        ok, offer_id, status = create_purchase_offer(ctx, pid, bid)
        if ok:
            print(f"       ✅ Oferta creada ID={offer_id} ({status})")
            bought += 1
            bought_pos.add(p["position"])
            available -= bid
            ctx.committed += bid
            ctx.pending_ids.add(pid)
            ctx.offers.append({"id": offer_id, "type": "purchase", "status": "waiting",
                                "amount": bid, "from": {"id": ctx.user_id},
                                "requestedPlayers": [{"id": pid}]})
            ctx.act("buy_offer_created", player_id=pid, player_name=p["name"], amount=bid, offer_id=offer_id)
            log_action("buy_offer_created", {"player_id": pid, "player_name": p["name"], "amount": bid,
                                             "offer_id": offer_id, "score": p["score"],
                                             "gain": p["gain"], "competition": competition},
                       "success")
        elif status == "dry_run":
            print("       🧪 Simulado: no se envía la puja")
        else:
            print(f"       ❌ {status}")
            ctx.act("buy_failed", player_id=pid, player_name=p["name"], reason=status)
            log_action("buy_offer_failed", {"player_id": pid, "player_name": p["name"], "reason": status}, "error")


def stage_lineup(ctx):
    if getattr(ctx, "abort", False):
        return
    print("\n  3. Alineación:")
    ok_lineup, why = lineup_is_complete(ctx)
    if not ok_lineup:
        print(f"     🔒 Alineación bloqueada: {why}")
        ctx.act("lineup_blocked", reason=why)
        log_action("lineup_blocked", {"reason": why}, "warning")
        return

    # Capitán y ariete solo existen si la liga los activa. En esta liga están
    # desactivados: antes se reenviaba la alineación en cada pasada para nada.
    use_captain = getattr(ctx, "captain_enabled", bool(CAPTAIN_KEY))
    use_striker = getattr(ctx, "striker_enabled", bool(STRIKER_KEY))
    if use_captain or use_striker:
        cap, striker = choose_captain_and_striker(ctx.opt_detail)
        ctx.captain_id = cap if use_captain else None
        ctx.striker_id = striker if use_striker else None
        nm = lambda i: (ctx.pool.get(i) or {}).get("name", i)
        print(f"     Capitán: {nm(ctx.captain_id)} · Ariete: {nm(ctx.striker_id)}")

    current_total = round(sum(e["score"] for e in ctx.pool.values() if e["id"] in ctx.lineup_ids), 3)
    best_total = ctx.opt_detail["total"]
    gain = best_total - current_total
    gain_pct = (gain / current_total * 100) if current_total > 0 else 100.0
    unavailable = [i for i in ctx.lineup_ids
                   if i not in ctx.pool or (ctx.pool[i]["status"] or "ok").lower() in BAD_STATUS]
    current_type = (ctx.lineup_info or {}).get("type")
    same = (ctx.opt_type == current_type and
            _lineup_lines(ctx.opt_ids, ctx.opt_type) == _lineup_lines(ctx.lineup_ids, current_type))
    extras = bool((use_captain and ctx.captain_id) or (use_striker and ctx.striker_id))
    # Con la misma plantilla, los huecos pueden cambiar sin que cambie el total estimado.
    moved = set(ctx.opt_ids) == set(ctx.lineup_ids) and not same

    if not same and (gain_pct >= MIN_LINEUP_GAIN * 100 or unavailable or moved):
        why_set = "titular no disponible" if unavailable and gain_pct < MIN_LINEUP_GAIN * 100 else f"{gain_pct:+.1f}%"
        print(f"     Mejora {current_total} → {best_total} ({why_set}). Cambiando a {ctx.opt_type}")
    elif extras:
        print("     Alineación igual de buena; se reenvía para fijar capitán/ariete")
    else:
        reason = "already_optimal" if same else "gain_below_threshold"
        print(f"     ⏸ Sin cambios ({reason}, {gain_pct:+.1f}%)")
        ctx.act("lineup_skipped", reason=reason, gain_pct=round(gain_pct, 2))
        log_action("lineup_skipped", {"reason": reason, "gain_pct": round(gain_pct, 2),
                                      "current": current_total, "best": best_total}, "info")
        return

    if not ctx.can_write():
        print("     ⚠️ Límite de escrituras alcanzado — la alineación NO se cambió")
        log_action("lineup_not_set_write_limit", {"writes": ctx.write_count}, "warning")
        return
    ok, resp = set_lineup(ctx, ctx.opt_ids, ctx.opt_type, ctx.captain_id, ctx.striker_id)
    used_alt = any(e["slot"] != e["position"] for k in ("def", "mid", "fwd")
                   for e in ctx.opt_detail[k] if "slot" in e)
    if not ok and used_alt and isinstance(resp, str) and resp.startswith("http_4") and ctx.can_write():
        # El uso de altPositions por la API aún no se ha probado en real: si se rechaza,
        # no nos quedamos sin alineación.
        print(f"     ⚠️ Multiposición rechazada ({resp[:80]}); se reintenta en posición real")
        log_action("multipos_rejected", {"reason": resp[:200]}, "warning")
        ctx.multipos = False
        ctx.recompute()
        best_total = ctx.opt_detail["total"] if ctx.opt_detail else best_total
        if lineup_is_complete(ctx)[0]:
            ok, resp = set_lineup(ctx, ctx.opt_ids, ctx.opt_type, ctx.captain_id, ctx.striker_id)
    if ok:
        out_ids = [i for i in ctx.lineup_ids if i not in ctx.opt_ids]
        in_ids = [i for i in ctx.opt_ids if i not in ctx.lineup_ids]
        out_names = [ctx.pool.get(i, {}).get("name", str(i)) for i in out_ids]
        in_names = [ctx.pool.get(i, {}).get("name", str(i)) for i in in_ids]
        diff_txt = ""
        if out_names or in_names:
            diff_txt = " | Salen: " + ", ".join(out_names) if out_names else ""
            if in_names:
                diff_txt += " | Entran: " + ", ".join(in_names)
        print(f"     ✅ Alineación actualizada a {ctx.opt_type}{diff_txt}")
        ctx.act("lineup_set", formation=ctx.opt_type, players=ctx.opt_ids, gain_pct=round(gain_pct, 2),
                captain=ctx.captain_id, striker=ctx.striker_id,
                out=out_names, entr=in_names)
        log_action("lineup_set", {"formation": ctx.opt_type, "total": best_total, "gain_pct": round(gain_pct, 2),
                                  "players": ctx.opt_ids, "captain": ctx.captain_id,
                                  "striker": ctx.striker_id, "out": out_names, "in": in_names}, "success")
    elif resp == "dry_run":
        print(f"     🧪 Simulado: alineación {ctx.opt_type} ({gain_pct:+.1f}%)")
    else:
        print(f"     ❌ Error alineación: {resp}")
        ctx.act("lineup_failed", reason=str(resp))
        log_action("lineup_failed", {"reason": str(resp), "formation": ctx.opt_type}, "error")
