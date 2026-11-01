"""Channel selection. One channel per deployment for now; per-account routing is
a one-line change once accounts carry a `channel` column."""
from __future__ import annotations

from ..config import settings
from .base import Channel, ChannelError
from .meta import MetaCloudChannel
from .stub import StubChannel


def get_channel() -> Channel:
    if settings.channel == "meta":
        return MetaCloudChannel()
    return StubChannel()


__all__ = ["Channel", "ChannelError", "StubChannel", "MetaCloudChannel", "get_channel"]
