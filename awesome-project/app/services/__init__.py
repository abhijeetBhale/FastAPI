"""Business logic and database access, one module per concern.

Services receive a `Session` and plain Python values and return models — they
never raise `HTTPException` and never see a `Request`, which is what keeps the
HTTP layer free of rules and the rules testable without a client. `rbac.py` and
`query.py` are shared helpers rather than aggregates.
"""
