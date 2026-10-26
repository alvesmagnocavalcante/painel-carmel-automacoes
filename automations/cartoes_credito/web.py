"""Entry point delegating to portal.web for Cartões de Crédito."""

from portal.web import Downloads, create_app, monotonic, serve

__all__ = ["Downloads", "create_app", "monotonic", "serve"]

if __name__ == "__main__":
    serve()
