from __future__ import annotations

"""Backward-compatible uvicorn shim for the canonical serving API app."""

import importlib
import sys

_api_module = importlib.import_module("rs_core.serving.api.app")
sys.modules[__name__] = _api_module
