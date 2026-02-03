# Backend testing

This backend uses **pytest**. The suite includes integration tests against the running `mongodb_instance` by reading:

- `mongodb-performance-monitor-210576-210587/mongodb_instance/db_connection.txt` (preferred), or
- `BACKEND_MONGO_URI` (fallback)

## Run

```bash
pytest
```

Tests live under:

- `tests/`

Notes:
- Collections in `perfmon` are cleaned between tests.
- FastAPI startup/shutdown runs (Mongo init, indexes, background loops).
