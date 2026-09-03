"""DEX Phone Management and provisioning integration for RCM 7021.

The package deliberately keeps all vendor behaviour behind the shared,
verified Fanvil/FiberMe driver.  Importing this package does not start workers
or touch the network; the application explicitly registers it after the DEX
migration has completed.
"""

from .migrations import run_migrations


def register_dex(app):
    """Register DEX routes.

    The existing application exposes its authentication and audit helpers as
    functions in ``app.py``.  Passing them into the package avoids a circular
    import and keeps DEX integration limited to this one call site.  The job
    executor is created only when a validated discovery request is submitted;
    importing or starting Flask never creates a worker thread.
    """
    from .routes import register_routes

    register_routes(app)
