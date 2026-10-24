"""Backward-compatible entry point delegating to portal.web."""

from portal.web import Downloads, create_app, monotonic, serve

__all__ = ["Downloads", "create_app", "monotonic", "serve"]

if __name__ == "__main__":
    serve()
