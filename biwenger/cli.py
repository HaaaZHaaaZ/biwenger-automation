"""Biwenger CLI utilities — probe, save_outputs, run, main."""
import sys
import os
import json
import time
import random
from datetime import datetime, timedelta

import requests

from biwenger import config as cfg
from biwenger import model
from biwenger import api
from biwenger.utils import log_action, acquire_instance_lock, rate_limit_active, set_rate_limit
from biwenger.writes import set_lineup
from biwenger.scoring import get_fixture_info, build_free_market, offer_player_ids
from biwenger.stages import (
    stage_cleanup_offers, stage_received_offers,
    stage_process_own_sale_offers, stage_sell_bench, stage_buy, stage_lineup
)


def probe(ctx):
    """Vuelca los campos reales de lineup para descubrir cómo guarda Biwenger capitán/ariete."""
    r = api.api("GET", "https://biwenger.as.com/api/v2/user?fields=*,lineup(*)",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        print(f"❌ Probe falló: {None if r is None else r.status_code}")
        return
    data = r.json().get("data", {})
    lineup = data.get("lineup") or {}
    with open(cfg.PROBE_FILE, "w", encoding="utf-8") as f:
        json.dump({"user_keys": sorted(data.keys()), "lineup": lineup}, f, indent=2, ensure_ascii=False)
    print(f"Claves de user:   {sorted(data.keys())}")
    print(f"Claves de lineup: {sorted(lineup.keys())}")
    print(f"Volcado completo en {cfg.PROBE_FILE}")
    print("Busca ahí el campo del capitán/ariete y ponlo en BIWENGER_CAPTAIN_KEY / BIWENGER_STRIKER_KEY.")


def save_outputs(ctx, now):
    state = {
        "date": now.isoformat(),
        "dry_run": cfg.DRY_RUN,
        "points": ctx.points,
        "balance": ctx.balance,
        "league_id": ctx.league_id,
        "user_id": ctx.user_id,
        "formation": ctx.opt_type,
        "current_lineup_ids": list(ctx.lineup_ids),
        "optimal_lineup_ids": ctx.opt_ids,
        "lineup_scores": {e["name"]: e["score"] for e in ctx.pool.values()},
        "lineup_total": ctx.opt_detail["total"] if ctx.opt_detail else None,
        "captain": ctx.captain_id,
        "striker": ctx.striker_id,
        "round": ctx.round_name,
        "next_kickoff": ctx.next_kickoff.isoformat() if ctx.next_kickoff else None,
        "hours_to_kickoff": ctx.hours_to_kickoff,
        "match_soon": ctx.match_soon,
        "rate_limited": ctx.rate_limited,
        "peticiones_usadas": model.REQ["count"],
        "writes": ctx.write_count,
        "actions": ctx.actions,
    }
    with open(cfg.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)

    todo = [
        "# Biwenger Auto-Trader v12",
        f"**Liga:** {ctx.league_id} · **Usuario:** {ctx.user_name} (ID {ctx.user_id}) · **Saldo:** €{ctx.balance:,}",
        f"**Puntos:** {ctx.points} · **Ejecución:** {now:%Y-%m-%d %H:%M}" + (" · DRY-RUN" if cfg.DRY_RUN else ""),
        "", "## Acciones",
    ]
    labels = {
        "offer_accepted": "✅ Oferta aceptada: {player_name} (€{amount:,})",
        "offer_rejected": "❌ Oferta rechazada: {player_name} (€{amount:,})",
        "offer_retracted": "↩️ Oferta propia retirada #{offer_id}",
        "sell_sub": "✅ En venta: {player_name} (€{price:,})",
        "buy_offer_created": "🔵 Puja por {player_name}: €{amount:,}",
        "lineup_set": "✅ Alineación: {formation}",
        "lineup_blocked": "🔒 Alineación bloqueada: {reason}",
        "lineup_skipped": "⏸ Alineación sin cambios ({reason})",
    }
    for a in ctx.actions:
        tpl = labels.get(a["type"])
        try:
            msg = tpl.format(**a) if tpl else f"• {a['type']}: {a}"
            if a["type"] == "lineup_set":
                out = a.get("out") or []
                entr = a.get("entr") or []
                if out or entr:
                    parts = []
                    if out:
                        parts.append("Salen: " + ", ".join(out))
                    if entr:
                        parts.append("Entran: " + ", ".join(entr))
                    msg += " (" + " | ".join(parts) + ")"
            todo.append(msg)
        except (KeyError, ValueError):
            todo.append(f"• {a['type']}")
    if not ctx.actions:
        todo.append("(sin acciones)")
    with open(cfg.TODO_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(todo) + "\n")

    # ── Informe detallado de entrega ─────────────────────────────────────────
    POS_LABEL = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    report = []
    report.append(f"Ejecución Biwenger Auto-Trader v{cfg.VERSION} — {now:%Y-%m-%d %H:%M} UTC")
    report.append("")
    report.append("✅ Login y Account OK")
    report.append(f"- {ctx.user_name} · {ctx.points} pts · €{ctx.balance:,} · Liga {ctx.league_id}")
    report.append(f"- Plantilla: {len(ctx.squad_ids)} jugadores · formación actual {ctx.lineup_info.get('type', '?')}")
    report.append(f"- Próximo partido: {ctx.next_kickoff:%a %d/%m %H:%M} (en {ctx.hours_to_kickoff} h) · {ctx.round_name}")
    report.append("")
    report.append(f"📊 Plantilla puntuada ({len(ctx.pool)}) — Mejor alineación: {ctx.opt_type} ({ctx.opt_detail['total'] if ctx.opt_detail else 'N/A'} pts esperados)")
    report.append("")
    if ctx.opt_detail:
        for key in ("gk", "def", "mid", "fwd"):
            for e in ctx.opt_detail[key]:
                report.append(POS_LABEL.get(e["position"], "?"))
                report.append(f"• Jugador: {e['name']}")
                report.append(f"• Score: {e['score']}")
                report.append("")
    report.append("Acciones:")
    # Ofertas recibidas
    received = [o for o in ctx.offers if o.get("status") == "waiting" and (o.get("to") or {}).get("id") == ctx.user_id and (o.get("from") or {}).get("id") != ctx.user_id]
    if received:
        for o in received:
            pids = offer_player_ids(o)
            pid = pids[0] if pids else None
            cp = ctx.catalog.get(str(pid)) if pid else None
            name = (cp or {}).get("name", f"id={pid}")
            amount = o.get("amount", 0) or 0
            mp = (cp or {}).get("price", 0) or 1
            ratio = amount / mp * 100
            report.append(f"- Ofertas recibidas: {len(received)} ({name} por €{amount:,}, ratio {ratio:.1f}%) → procesada")
    else:
        report.append("- Ofertas recibidas: 0")
    # Ventas
    sell_actions = [a for a in ctx.actions if a['type'] in ('sell_sub', 'sell_sub_failed')]
    if sell_actions:
        report.append("- Ventas de suplentes: " + "; ".join(f"{a.get('player_name', a.get('player_id'))}" + (" (no se pudo vender)" if a['type'] == 'sell_sub_failed' else "") for a in sell_actions))
    else:
        report.append("- Ventas de suplentes: ninguna")
    # Compras
    buy_actions = [a for a in ctx.actions if a['type'] in ('buy_offer_created', 'buy_failed')]
    if buy_actions:
        report.append("- Compras: " + "; ".join(f"{a.get('player_name', a.get('player_id'))}" for a in buy_actions))
    else:
        report.append("- Compras: sin cupo o sin mejoras")
    # Alineación
    lineup_action = next((a for a in ctx.actions if a['type'] in ('lineup_set', 'lineup_skipped', 'lineup_blocked')), None)
    if lineup_action:
        if lineup_action['type'] == 'lineup_set':
            report.append(f"- Alineación: ✅ Actualizada a {lineup_action.get('formation')} ({lineup_action.get('gain_pct', 0):+.1f}%)")
            out = lineup_action.get('out') or []
            entr = lineup_action.get('entr') or []
            if out:
                report.append(f"  - Salen: {', '.join(out)}")
            if entr:
                report.append(f"  - Entran: {', '.join(entr)}")
            if lineup_action.get('captain'):
                nm = (ctx.pool.get(lineup_action['captain']) or {}).get('name', lineup_action['captain'])
                report.append(f"  - Capitán: {nm}")
            if lineup_action.get('striker'):
                nm = (ctx.pool.get(lineup_action['striker']) or {}).get('name', lineup_action['striker'])
                report.append(f"  - Ariete: {nm}")
        elif lineup_action['type'] == 'lineup_skipped':
            report.append(f"- Alineación: ⏸ Sin cambios ({lineup_action.get('reason')}, {lineup_action.get('gain_pct', 0):+.1f}%)")
        else:
            report.append(f"- Alineación: 🔒 Bloqueada ({lineup_action.get('reason')})")
    else:
        report.append("- Alineación: sin evaluación")
    report.append("")
    writes = ctx.write_count
    reqs = model.REQ['count']
    report.append(f"Resumen: {len(ctx.actions)} acciones, {writes} writes, {reqs} peticiones. Sin errores críticos.")
    report.append("")
    # Incidencias
    incidencias = []
    if len(ctx.squad_ids) + len(ctx.pending_ids) >= cfg.MAX_TEAM_SIZE:
        incidencias.append("Cupo 16/16 bloqueado — no hay cupo para comprar. Aceptar ofertas de máquina ≥90% sobre suplentes en venta liberaría cupo.")
    for a in ctx.actions:
        if a['type'] == 'sell_sub_failed':
            incidencias.append(f"{a.get('player_name', a.get('player_id'))}: {a.get('reason')}")
    if incidencias:
        report.append("⚠️ Incidencias: " + " | ".join(incidencias))
    report.append("")
    report.append("To stop or manage this job, send me a new message (e.g. \"stop reminder Biwenger Daily Auto-Trader\").")
    print("\n" + "\n".join(report))


def run(probe_only=False, live=False):
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        print("Otra instancia en ejecución, saliendo", file=sys.stderr)
        sys.exit(0)
    global DRY_RUN
    DRY_RUN = not live   # sin --live NUNCA se escribe, aunque BIWENGER_DRY_RUN=false
    now = datetime.now()
    print(f"\n{'=' * 60}\nBiwenger Auto-Trader v{cfg.VERSION} — {now:%Y-%m-%d %H:%M}"
          + (" [DRY-RUN]" if DRY_RUN else "") + f"\n{'=' * 60}")

    until = rate_limit_active()
    if until:
        print(f"⏸ Rate limit activo hasta {until:%Y-%m-%d %H:%M}. No se hace nada.")
        return 6
    if cfg.START_JITTER_MAX > 0:
        time.sleep(random.uniform(0, cfg.START_JITTER_MAX))

    ctx = model.Ctx()
    ctx.dry_run = DRY_RUN
    if os.path.exists(cfg.UNKNOWN_STATE_PATH):
        ctx.read_only = True
        print("MODO LECTURA: unknown_state presente, no se escribirá")
    print("Modo:", "LIVE" if not DRY_RUN else "DRY-RUN")
    log_action("run_mode", {"mode": "LIVE" if not DRY_RUN else "DRY-RUN",
                            "read_only": ctx.read_only, "version": cfg.VERSION}, "info")
    ctx.session = requests.Session()
    api.set_session(ctx.session)
    model.set_wait_budget(ctx.wait_budget)
    model.set_ctx(ctx)
    try:
        ctx.token = cfg.TOKEN or api.login()
        print("✅ Autenticado")
        (ctx.league_id, ctx.user_id, ctx.balance, ctx.points, ctx.user_name) = api.get_account(ctx.token)
        print(f"\n--- Account ---\n  {ctx.user_name} | {ctx.points} pts | €{ctx.balance:,} | liga {ctx.league_id}")

        if probe_only:
            probe(ctx)
            return 0

        # Datos
        squad_ids, lineup_info, lineup_players = api.get_squad(ctx)
        if lineup_info is None:
            print("❌ No se pudo obtener la plantilla")
            return 1
        ctx.squad_ids, ctx.lineup_info = squad_ids, lineup_info
        ctx.lineup_ids = lineup_info.get("playersID") or []
        print(f"  Plantilla: {len(ctx.squad_ids)} jugadores · formación actual {lineup_info.get('type', '?')}")

        ctx.catalog, cat_teams = api.get_catalog(ctx)
        print(f"  Catálogo: {len(ctx.catalog)} jugadores · {len(cat_teams)} equipos")
        if not ctx.catalog:
            print("❌ Sin catálogo: no se actúa")
            log_action("no_catalog", {}, "error")
            return 1

        ctx.diff_map, ctx.games_map, ctx.round_name, kickoffs = get_fixture_info(lineup_players)
        ctx.round_name = ctx.round_name or api.get_round_name(ctx)
        future = [d for d in kickoffs.values() if d >= now - timedelta(hours=3)]
        if future:
            ctx.next_kickoff = min(future)
            ctx.hours_to_kickoff = round((ctx.next_kickoff - now).total_seconds() / 3600, 1)
            ctx.match_soon = ctx.hours_to_kickoff <= cfg.MATCH_SOON_HOURS
            print(f"  Próximo partido: {ctx.next_kickoff:%a %d/%m %H:%M} (en {ctx.hours_to_kickoff} h) "
                  f"· {ctx.round_name or ''}")
        else:
            ctx.match_soon = True  # sin fechas: conservador
            print("  ⚠️ Sin fechas de partidos: se asume partido cercano (no se vende por score bajo)")
            log_action("no_kickoff_dates", {}, "warning")
        print(f"  Dificultad conocida para {len(ctx.diff_map)} equipos")

        ctx.offers = api.get_offers(ctx)
        free_sales, own_sales = api.get_market(ctx)
        ctx.my_sale_ids = {(s.get("player") or {}).get("id") for s in own_sales}
        ctx.free_market = build_free_market(ctx, free_sales)

        # Mostrar jugadores actualmente en venta (propias)
        if own_sales:
            print(f"  📋 Jugadores actualmente en venta ({len(own_sales)}):")
            for s in own_sales:
                p = s.get("player") or {}
                pid = p.get("id")
                price = s.get("price", 0)
                cp = ctx.catalog.get(str(pid)) if pid else None
                name = cp.get("name", f"id={pid}") if cp else p.get("name", f"id={pid}")
                print(f"     - {name} (id={pid}) · €{price:,}")
        else:
            print(f"  📋 Jugadores actualmente en venta: 0")

        print(f"  Mercado: {len(free_sales)} libres · {len(own_sales)} propias · "
              f"{len(ctx.offers)} ofertas en total")

        ctx.recompute()
        if not ctx.opt_ids:
            print("⚠️ No hay combinación válida de alineación (¿sin porteros?)")
            log_action("lineup_eval", {"result": "no_valid_lineup"}, "warning")
        else:
            print(f"\n--- Plantilla puntuada ({len(ctx.pool)}) ---")
            for e in sorted(ctx.pool.values(), key=lambda x: x["score"], reverse=True):
                gm = ctx.games_map.get(e["team_id"], {})
                print(f"  {e['name']:20} {cfg.POS_NAMES.get(e['position'], '?'):3} score={e['score']:6.3f} "
                      f"vs {gm.get('rival', '?')} ({gm.get('cond', '?')}) · {e['why']}")
            print(f"\n  Mejor alineación: {ctx.opt_type} (total={ctx.opt_detail['total']})")
            log_action("lineup_eval", {"formation": ctx.opt_type, "total": ctx.opt_detail["total"]}, "info")

        # Acciones
        print("\n--- Acciones ---")
        stage_cleanup_offers(ctx)
        stage_received_offers(ctx)
        stage_process_own_sale_offers(ctx)
        ctx.recompute()
        stage_sell_bench(ctx)
        stage_buy(ctx)
        stage_lineup(ctx)

    except model.RateLimited as e:
        ctx.rate_limited = True
        until = set_rate_limit()
        print(f"\n🚫 429 (rate limit) en {e}. Pausa hasta {until:%Y-%m-%d %H:%M}")
        log_action("rate_limited", {"until": until.isoformat()}, "error")
        save_outputs(ctx, now)
        return 6
    except model.OldVersion:
        print("\n❌ 'Old version': sube BIWENGER_VERSION (DevTools → Network → cabecera x-version)")
        log_action("old_version", {"x_version": cfg.APP_VERSION}, "error")
        return 5
    except model.AuthError:
        print("\n❌ 401: token o credenciales inválidos")
        log_action("auth_error", {}, "error")
        return 3

    save_outputs(ctx, now)
    print(f"\n  ✅ State: {cfg.STATE_FILE}\n  ✅ Todo:  {cfg.TODO_FILE}")
    print(f"\n{'=' * 60}\n✅ Ejecución completada — {len(ctx.actions)} acciones, "
          f"{ctx.write_count} writes, {model.REQ['count']} peticiones\n{'=' * 60}")
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Biwenger Auto-Trader")
    ap.add_argument("--live", action="store_true", help="permite escrituras reales (sin esto: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="simula, sin escrituras (comportamiento por defecto)")
    ap.add_argument("--probe", action="store_true", help="vuelca los campos de lineup")
    a = ap.parse_args(argv)
    if a.live and a.dry_run:
        ap.error("--live y --dry-run son incompatibles")
    try:
        return run(probe_only=a.probe, live=a.live)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR FATAL: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())