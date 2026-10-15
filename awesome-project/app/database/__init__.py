"""Database foundation: the connection, and the declarative Base.

`app/database/database.py` owns the engine, the session factory and the
`get_db` dependency; `base.py` owns `Base` and the shared `utcnow()` clock.
Splitting them keeps the import graph acyclic — `app/models/` needs `Base` and
nothing else, while only the app and the scripts need an engine.
"""
