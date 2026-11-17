"""Imports every model module so Base.metadata knows every table.

Alembic and the test suite import this; application code imports models directly.
"""

from markx.accounts import models as accounts_models
from markx.analytics import models as analytics_models
from markx.audit import models as audit_models
from markx.catalog import models as catalog_models
from markx.core import models as core_models
from markx.delivery import models as delivery_models
from markx.notifications import models as notifications_models
from markx.offers import models as offers_models
from markx.ops import models as ops_models
from markx.orders import models as orders_models
from markx.payments import models as payments_models
from markx.search import models as search_models
from markx.sellers import models as sellers_models
from markx.trust import models as trust_models
from markx.worker import models as worker_models

__all__ = [
    "accounts_models",
    "analytics_models",
    "audit_models",
    "catalog_models",
    "core_models",
    "delivery_models",
    "notifications_models",
    "offers_models",
    "ops_models",
    "orders_models",
    "payments_models",
    "search_models",
    "sellers_models",
    "trust_models",
    "worker_models",
]
