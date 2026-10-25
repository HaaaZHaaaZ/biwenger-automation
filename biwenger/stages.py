"""Biwenger stages — todas las etapas del flujo de ejecución."""
from biwenger import config as cfg
from biwenger import model
from biwenger.utils import log_action
from biwenger.writes import sell_player, answer_offer, create_purchase_offer, set_lineup, retract_offer
from biwenger.scoring import (
    build_smart_lineup, offer_player_ids, lineup_is_complete,
    build_free_market
)
from biwenger.config import (
    BAD_STATUS, POS_NAMES, MIN_P_START_BUY, MATCH_SOON_HOURS,
    SELL_BENCH_WHEN_LINEUP_READY, MIN_LINEUP_GAIN, BUY_MARGIN,
    BID_LOW, BID_MID, BID_HIGH, MAX_BID_PCT, BID_PLUS_ONE,
    CAPTAIN_MAX_VALUE, CAPTAIN_KEY, STRIKER_KEY,
    ACCEPT_NORMAL, ACCEPT_HIGH, ACCEPT_INJURED, MAX_DROP_PCT,
    ACCEPT_MACHINE_MIN, MAX_TEAM_SIZE, SELL_SCORE_MIN
)


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
        if st in BAD_STATUS and ctx.can_write():
            ok, msg = retract_offer(ctx, o.get("id"))
            print(f"  ↩️ Retiro oferta #{o.get('id')} por {(cp or {}).get('name', pid)} ({st}): {msg}")
            if ok:
                ctx.write_count += 1
                ctx.pending_ids.discard(pid)
                ctx.act("offer_retracted", offer_id=o.get("id"), player_id=pid, reason=st)
                log_action("offer_retracted", {"offer_id": o.get("id"), "player_id": pid, "reason": st}, "success")
                continue
        keep.append(o)

    committed = sum(o.get("amount", 0) or 0 for o in keep)
    limit = ctx.balance - ctx.cushion()
    if committed > limit:
        keep.sort(key=lambda o: scores.get((offer_player_ids(o) or [0])[0], 0))
        while keep and committed > limit and ctx.can_write():
            o = keep[0]
            ok, msg = retract_offer(ctx, o.get("id"))
            if not ok:
                break
            keep.pop(0)
            committed -= o.get("amount", 0) or 0
            ctx.write_count += 1
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
    print("\n  0. Ofertas recibidas:")
    received = [o for o in ctx.offers
                if o.get("status") == "waiting"
                and (o.get("to") or {}).get("id") == ctx.user_id
                and (o.get("from") or {}).get("id") != ctx.user_id]
    if not received:
        print("     ✅ No hay ofertas recibidas")
        return
    sold = set()
    for o in received:
        if not ctx.can_write():
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
        ids_a, _, detail_a, _ = build_smart_lineup(after, ctx.catalog, ctx.diff_map, ctx.games_map)
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

        accept, reason = False, ""
        if not valid_after:
            reason = "dejaría posiciones sin cubrir"
        elif ratio >= ACCEPT_HIGH:
            accept, reason = True, f"oferta ≥ {ACCEPT_HIGH*100:.0f}% del mercado"
        elif ratio >= ACCEPT_NORMAL and has_replacement:
            accept, reason = True, f"oferta ≥ {ACCEPT_NORMAL*100:.0f}% y hay reemplazo (caída {drop*100:.1f}%)"
        elif injured and ratio >= ACCEPT_INJURED:
            accept, reason = True, f"{st} y oferta ≥ {ACCEPT_INJURED*100:.0f}%"
        elif (ratio >= ACCEPT_MACHINE_MIN and pid in ctx.my_sale_ids
              and pid not in ctx.opt_ids and entry.get("score", 99) < SELL_SCORE_MIN):
            # Desbloqueo de cupo: jugador de banquillo ya puesto en venta y de valor
            # bajo. Completar la venta libera un hueco de plantilla y da caja.
            accept, reason = True, (f"desbloqueo de cupo: en venta, score {entry.get('score', 0):.2f} "
                                    f"y oferta ≥ {ACCEPT_MACHINE_MIN*100:.0f}% del mercado")
        else:
            applicable = ACCEPT_INJURED if injured else (ACCEPT_NORMAL if has_replacement else ACCEPT_MACHINE_MIN)
            reason = (f"ratio {ratio*100:.1f}% insuficiente (mínimo aplicable {applicable*100:.0f}%) "
                      f"o sin reemplazo")

        if accept:
            ok, msg = answer_offer(ctx, oid, "accepted")
            if ok:
                print(f"       ✅ Aceptada — {reason}")
                ctx.write_count += 1
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
                ctx.write_count += 1
                ctx.act("offer_rejected", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_rejected", {"offer_id": oid, "player_id": pid, "player_name": name,
                                              "amount": amount, "reason": reason}, "success")
            else:
                print(f"       ❌ Error rechazando: {msg}")
                log_action("offer_reject_failed", {"offer_id": oid, "reason": msg}, "error")


def stage_process_own_sale_offers(ctx):
    """Procesa ofertas recibidas en jugadores que ya tenemos en venta."""
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
                ctx.write_count += 1
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
                ctx.write_count += 1
                ctx.act("offer_rejected", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_rejected", {"offer_id": oid, "player_id": pid, "player_name": name, "amount": amount, "reason": reason}, "success")
            else:
                print(f"       ❌ Error rechazando: {msg}")


def stage_sell_bench(ctx):
    if getattr(ctx, "abort", False):
        return
    """Vende suplentes lesionados o de score bajo solo si hay mejor reemplazo en el mercado."""
    print("\n  1. Ventas de suplentes:")
    starters = set(ctx.opt_ids)
    sold = 0
    for e in sorted(ctx.pool.values(), key=lambda x: x["score"]):
        if e["id"] in starters or e["id"] in ctx.my_sale_ids:
            continue
        if sold >= cfg.MAX_SELLS or not ctx.can_write():
            break
        if len(ctx.squad_ids) - sold <= cfg.MIN_SQUAD:
            print(f"     ⏸ Plantilla mínima ({cfg.MIN_SQUAD}) — no se vende más")
            break
        st = (e.get("status") or "ok").lower()
        bad, low = st in BAD_STATUS, e["score"] < SELL_SCORE_MIN
        if not (bad or low):
            continue
        if low and not bad and ctx.match_soon:
            # Opción B: si la alineación ya está cerrada (11 titulares listos),
            # los suplentes no aportan puntos y no hay riesgo de quedarse corto.
            lineup_ready = len(ctx.opt_ids) >= 11
            if lineup_ready and SELL_BENCH_WHEN_LINEUP_READY:
                print(f"     🔓 {e['name']} (score={e['score']:.3f}) — alineación cerrada, se vende")
            else:
                print(f"     ⏸ {e['name']} (score={e['score']:.3f}) — partido cerca y alineación "
                      f"sin cerrar ({len(ctx.opt_ids)}/11), se mantiene")
                continue
        has_repl = any(r["position"] == e["position"] and r["status"] == "ok"
                       and r["score"] > e["score"] and r["p_start"] >= MIN_P_START_BUY
                       for r in ctx.free_market)
        if not has_repl:
            print(f"     ⏸ {e['name']} ({st}, score={e['score']:.3f}) — sin mejor reemplazo en el mercado")
            continue
        price = ctx.catalog.get(str(e["id"]), {}).get("price", 0)
        reason = f"status={st}" if bad else f"score_bajo={e['score']:.3f}"
        ok, msg, used = sell_player(ctx, e["id"], max(price, 1))
        if ok:
            print(f"     ✅ {e['name']} en venta a €{used:,} ({reason})")
            ctx.write_count += 1
            sold += 1
            ctx.my_sale_ids.add(e["id"])
            ctx.act("sell_sub", player_id=e["id"], player_name=e["name"], price=used)
            log_action("sell_sub", {"player_id": e["id"], "player_name": e["name"],
                                    "reason": reason, "price": used}, "success")
        else:
            print(f"     ❌ {e['name']}: {msg}")
            ctx.act("sell_sub_failed", player_id=e["id"], reason=msg)
            log_action("sell_sub_failed", {"player_id": e["id"], "player_name": e["name"], "reason": msg}, "error")
    if sold == 0:
        print("     ✅ Nada que vender ahora")


def stage_buy(ctx):
    if getattr(ctx, "abort", False):
        return
    """Pujas dinámicas por jugadores del mercado libre que mejoren a los titulares."""
    print("\n  2. Compras:")
    if ctx.balance < 0:
        print("     🚨 Saldo negativo: no se compra (el saldo negativo resta puntos)")
        log_action("balance_negative", {"balance": ctx.balance}, "warning")
        return
    if cfg.MAX_SQUAD and len(ctx.squad_ids) >= cfg.MAX_SQUAD:
        print(f"     ⏸ Plantilla completa ({cfg.MAX_SQUAD})")
        return
    # El cupo de la liga cuenta jugadores + ofertas abiertas. Si ya está al máximo
    # la API responde 403 "Maximum team size reached": es mejor no gastar la
    # petición y explicar por qué no se puja.
    own_open = {pid for o in ctx.offers
                if o.get("status") == "waiting" and (o.get("from") or {}).get("id") == ctx.user_id
                for pid in offer_player_ids(o)}
    occupied = len(ctx.squad_ids) + len(own_open)
    if occupied >= MAX_TEAM_SIZE:
        on_sale = len(ctx.my_sale_ids)
        print(f"     ⏸ Cupo de liga completo ({occupied}/{MAX_TEAM_SIZE}): "
              f"{len(ctx.squad_ids)} jugadores ({len(ctx.squad_ids)-on_sale} libres + "
              f"{on_sale} en venta) + {len(own_open)} ofertas abiertas")
        print(f"        Solo se libera cupo al COMPLETAR una venta: se aceptan las ofertas")
        print(f"        de la máquina (≥{ACCEPT_MACHINE_MIN*100:.0f}%) sobre suplentes en venta.")
        log_action("buy_check", {"result": "team_full", "occupied": occupied,
                                 "max": MAX_TEAM_SIZE, "on_sale": on_sale}, "info")
        return

    worst = {}
    if ctx.opt_detail:
        for key in ("gk", "def", "mid", "fwd"):
            for e in ctx.opt_detail[key]:
                worst[e["position"]] = min(worst.get(e["position"], 99), e["score"])

    cands = [r for r in ctx.free_market if r["status"] == "ok" and r["id"] not in ctx.pending_ids
             and r["id"] not in ctx.squad_ids and r["p_start"] >= MIN_P_START_BUY]
    cands.sort(key=lambda r: r["score"], reverse=True)
    print(f"     Mercado libre evaluado: {len(ctx.free_market)} · candidatos: {len(cands)}")
    for r in cands[:5]:
        print(f"       {r['name']:22} {POS_NAMES.get(r['position'], '?'):3} score={r['score']:6.3f} €{r['price']:,}")

    upgrades = []
    for r in cands:
        w = worst.get(r["position"])
        if w is None:
            continue
        if r["score"] > w * (1 + BUY_MARGIN) and r["price"] <= ctx.balance:
            upgrades.append({**r, "peor_titular": w, "gain": r["score"] - w})
    upgrades.sort(key=lambda r: r["gain"], reverse=True)
    if not upgrades:
        print("     ✅ Ningún jugador del mercado mejora a los titulares")
        log_action("buy_check", {"result": "no_upgrade_available", "evaluados": len(cands)}, "info")
        return

    available = ctx.balance - ctx.committed - ctx.cushion()
    print(f"     💰 Saldo €{ctx.balance:,} · comprometido €{ctx.committed:,} · "
          f"colchón €{ctx.cushion():,.0f} · disponible €{available:,.0f}")

    bought, bought_pos = 0, set()
    for p in upgrades:
        if bought >= cfg.MAX_BUYS or not ctx.can_write():
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
        print(f"     → {p['name']} ({POS_NAMES.get(p['position'], '?')}) mercado €{price:,} · "
              f"score {p['score']} vs peor titular {p['peor_titular']:.3f} · "
              f"competencia {competition} · puja €{bid:,}")
        if bid > available:
            print(f"       ⚠️ Excede el saldo disponible — se omite")
            continue
        ok, offer_id, status = create_purchase_offer(ctx, pid, bid)
        if ok:
            print(f"       ✅ Oferta creada ID={offer_id} ({status})")
            ctx.write_count += 1
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
                                             "peor_titular": p["peor_titular"], "competition": competition},
                       "success")
        else:
            print(f"       ❌ {status}")
            ctx.act("buy_failed", player_id=pid, reason=status)
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

    if CAPTAIN_KEY or STRIKER_KEY:
        ctx.captain_id, ctx.striker_id = model.choose_captain_and_striker(ctx.opt_detail)
        nm = lambda i: (ctx.pool.get(i) or {}).get("name", i)
        print(f"     Capitán: {nm(ctx.captain_id)} · Ariete: {nm(ctx.striker_id)}")

    current_total = round(sum(e["score"] for e in ctx.pool.values() if e["id"] in ctx.lineup_ids), 3)
    best_total = ctx.opt_detail["total"]
    gain = best_total - current_total
    gain_pct = (gain / current_total * 100) if current_total > 0 else 100.0
    unavailable = [i for i in ctx.lineup_ids
                   if i not in ctx.pool or (ctx.pool[i]["status"] or "ok").lower() in BAD_STATUS]
    same = ctx.opt_ids == ctx.lineup_ids
    extras = bool(CAPTAIN_KEY or STRIKER_KEY)

    if not same and (gain_pct >= MIN_LINEUP_GAIN * 100 or unavailable):
        why_set = "titular no disponible" if unavailable and gain_pct < MIN_LINEUP_GAIN * 100 else f"{gain_pct:+.1f}%"
        print(f"     Mejora {current_total} → {best_total} ({why_set}). Cambiando a {ctx.opt_type}")
    elif extras and ctx.captain_id:
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
        ctx.write_count += 1
        ctx.act("lineup_set", formation=ctx.opt_type, players=ctx.opt_ids,
                captain=ctx.captain_id, striker=ctx.striker_id,
                out=out_names, entr=in_names)
        log_action("lineup_set", {"formation": ctx.opt_type, "total": best_total, "gain_pct": round(gain_pct, 2),
                                  "players": ctx.opt_ids, "captain": ctx.captain_id,
                                  "striker": ctx.striker_id, "out": out_names, "in": in_names}, "success")
    else:
        print(f"     ❌ Error alineación: {resp}")
        ctx.act("lineup_failed", reason=str(resp))
        log_action("lineup_failed", {"reason": str(resp), "formation": ctx.opt_type}, "error")