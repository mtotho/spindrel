"""Top-level package exposing Spindrel's widget author surface.

Widget bundles import handlers via ``from spindrel.widget import on_action, ctx``.
Implementation lives in ``app.services.widget_py`` — this package is a thin
re-export so widget.py files don't have to know about the app namespace.
"""
