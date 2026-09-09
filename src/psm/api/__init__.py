"""HTTP surface and the demonstration UI.

`psm.api.app` is the FastAPI application; `psm.api.ui` is the single page it
serves. Everything the UI can do, the JSON API can do, and the CLI can do -
there is no capability that exists only behind a button.
"""

from __future__ import annotations

__all__ = ["app"]


def __getattr__(name: str):  # pragma: no cover - import convenience
    if name == "app":
        from psm.api.app import app

        return app
    raise AttributeError(name)
