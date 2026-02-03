# Backend tests (pytest)

These tests include **integration coverage** against the running `mongodb_instance` by reading:

- `mongodb-performance-monitor-210576-210587/mongodb_instance/db_connection.txt` (preferred), or
- `BACKEND_MONGO_URI` (fallback)

## Run

From `mongodb-performance-monitor-210576-210586/performance_monitor_backend/`:

```bash
pytest
```

Notes:
- Tests clean `perfmon` collections between cases to avoid cross-test coupling.
- FastAPI startup events run (Mongo connect + index init + background loops). Interactions that depend on evaluator loops use short polling.
