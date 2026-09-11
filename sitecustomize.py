"""Runtime guard for the adaptive scalp strategy.

Python imports ``sitecustomize`` automatically when it is on sys.path. The live
runner sets the repository root as the working directory and exposes ``src`` on
PYTHONPATH, so this small compatibility layer can enforce a scalp-specific ADX
threshold without changing the large strategy module in-place.
"""
from __future__ import annotations

import json
from pathlib import Path


def _patch_adaptive_scalp_adx() -> None:
    try:
        from use_cases.strategy import AdaptiveStrategy
    except Exception:
        return

    settings_path = Path.cwd() / "settings.json"
    threshold = 20.0
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        threshold = float(data.get("adaptive_scalp_adx_threshold", threshold))
    except Exception:
        pass

    original = getattr(AdaptiveStrategy, "_build_scalp_entry_signal", None)
    if original is None or getattr(original, "_adaptive_adx_guard", False):
        return

    def guarded(self, code, price, position_qty, atr, adx, volatility):
        # The original implementation effectively used adx_threshold * 0.45.
        # This wrapper adds a dedicated, explicit minimum for scalp entries.
        if adx is None or float(adx) < threshold:
            return None
        return original(self, code, price, position_qty, atr, adx, volatility)

    guarded._adaptive_adx_guard = True
    AdaptiveStrategy._build_scalp_entry_signal = guarded


_patch_adaptive_scalp_adx()
