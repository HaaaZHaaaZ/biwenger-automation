#!/usr/bin/env python3
"""Script de validación de estrategia en cuentas de prueba (dry-run)."""

import os
import sys
import argparse

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from biwenger_daily import run

# Cuentas de prueba registradas
TEST_ACCOUNTS = {
    "ernestine": {
        "email": "1228ernestine@punkproof.com",
        "league": "1453748",
        "user": "14492359"
    },
    "diana": {
        "email": "dianaelectric@uberip.com",
        "league": "1698202",
        "user": "14492365"
    }
}

def validate_account(account_name, dry_run=True):
    """Ejecuta la estrategia en una cuenta de prueba."""
    acc = TEST_ACCOUNTS.get(account_name)
    if not acc:
        print(f"❌ Cuenta '{account_name}' no encontrada.")
        return False

    print(f"--- Validando cuenta: {account_name} ({acc['email']}) ---")
    
    # Configurar entorno para la cuenta de prueba
    os.environ["BIWENGER_EMAIL"] = acc["email"]
    os.environ["BIWENGER_LEAGUE_ID"] = acc["league"]
    os.environ["BIWENGER_USER_ID"] = acc["user"]
    os.environ["BIWENGER_DRY_RUN"] = str(dry_run)
    os.environ["BIWENGER_MAX_WRITES"] = "8"
    os.environ["BIWENGER_MAX_BUYS"] = "2"
    os.environ["BIWENGER_MAX_SELLS"] = "6"

    try:
        # Ejecutar biwenger_daily
        run()
        print(f"✅ Validación de {account_name} completada.")
        return True
    except Exception as e:
        print(f"❌ Error validando {account_name}: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Valida la estrategia de Biwenger.")
    parser.add_argument("--account", choices=["ernestine", "diana", "all"], default="all", help="Cuenta a validar")
    parser.add_argument("--live", action="store_true", help="Desactivar dry-run (EJECUCIÓN REAL)")
    
    args = parser.parse_args()
    dry_run = not args.live

    if dry_run:
        print("⚠️  Modo DRY-RUN activo: no se realizarán escrituras reales.")
    else:
        print("🚀 MODO LIVE ACTIVO: SE REALIZARÁN ESCRITURAS REALES EN LAS CUENTAS DE PRUEBA.")

    success = True
    if args.account == "all":
        for name in TEST_ACCOUNTS:
            if not validate_account(name, dry_run):
                success = False
    else:
        success = validate_account(args.account, dry_run)

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
