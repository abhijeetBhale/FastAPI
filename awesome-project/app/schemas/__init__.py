"""The Pydantic contracts — what the API accepts and what it returns.

Split by direction: `requests/` validates inbound payloads, `responses/` shapes
outbound ones (and doubles as the OpenAPI documentation). `errors.py` renders
validation failures as JSON-safe detail lists, and `validators.py` holds the
reusable field validators. A schema describes a payload; it does not query.
"""
