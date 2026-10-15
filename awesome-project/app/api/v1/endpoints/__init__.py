"""The route handlers for version 1, one module per resource.

Each module exposes an `APIRouter` holding only *its* paths relative to the
version prefix; the prefix is applied once in `app/api/v1/api.py`, never here.
"""
