"""Pydantic schemas shared across routers and services.

Schemas live here (not in `app/routers/`) so that services can import them
without creating router → service → router import cycles. Routers re-export
from this package to keep their public API stable.
"""
