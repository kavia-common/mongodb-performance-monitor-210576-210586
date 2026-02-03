"""Business-logic layer (MongoDB-backed for instances and metrics; some insights remain stubbed).

Alerts engine services live in:
- alerts_service.py (CRUD + list feed)
- alerts_evaluator.py (background rule evaluation loop)
"""

# Import side-effects are intentionally avoided here; modules are imported by routers/services as needed.
