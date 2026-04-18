import uuid
from datetime import datetime, timezone

from app.db.models import SecretValue


def build_secret_value(**overrides) -> SecretValue:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        name=f"MY_SECRET_{suffix.upper()}",
        value="plaintext-test-value",
        description="",
        created_by=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return SecretValue(**{**defaults, **overrides})
