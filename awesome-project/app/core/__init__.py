"""Cross-cutting foundations: settings, security and error handling.

Nothing here imports from `api/`, `services/` or `models/` at module import
time beyond `models.user` (a type annotation), so every layer may import this
package without a cycle.
"""
