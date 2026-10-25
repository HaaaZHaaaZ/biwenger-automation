"""Biwenger package — re-exports all modules for backward compatibility.

biwenger_daily.py imports everything from here so that monkeypatch.setattr(bw, "api", spy)
works for any code that accesses api via biwenger_daily.api.
The actual implementations live in biwenger.{config,model,utils,api,writes,scoring,stages,cli}.
"""
from biwenger.config import *
from biwenger.model import *
from biwenger.utils import *
from biwenger.scoring import *

# Import api and writes LAST to avoid circular imports
from biwenger.api import *
from biwenger.writes import *

# Import stages and cli
from biwenger.stages import *
from biwenger.cli import *

# Explicitly re-export _api_write (used by AST test, prefixed with _ so not in *)
from biwenger.api import _api_write

# Ensure writes module sees the same api reference as biwenger_daily
def _sync_api_refs():
    try:
        import biwenger.api as _api_mod
        import biwenger.writes as _writes_mod
        _writes_mod.api = _api_mod.api
    except Exception:
        pass  # Deferred if not ready

_sync_api_refs()