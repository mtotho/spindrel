import random
import uuid
from datetime import datetime, timezone

from app.db.models import DockerStack

_MINIMAL_COMPOSE = "version: '3'\nservices:\n  app:\n    image: nginx"


def build_docker_stack(**overrides) -> DockerStack:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        name=f"test-stack-{suffix}",
        description=None,
        created_by_bot="test-bot",
        channel_id=None,
        compose_definition=_MINIMAL_COMPOSE,
        project_name=f"proj-{suffix}",
        status=random.choice(["running", "stopped"]),
        error_message=None,
        network_name=None,
        container_ids={},
        exposed_ports={},
        source="bot",
        integration_id=None,
        last_started_at=None,
        last_stopped_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return DockerStack(**{**defaults, **overrides})
