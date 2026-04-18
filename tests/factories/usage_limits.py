import random
import uuid
from datetime import datetime, timezone

from app.db.models import UsageLimit


def build_usage_limit(**overrides) -> UsageLimit:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        scope_type=random.choice(["model", "bot"]),
        scope_value=f"scope-{suffix}",
        period=random.choice(["daily", "monthly"]),
        limit_usd=float(random.randint(1, 100)),
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return UsageLimit(**{**defaults, **overrides})
