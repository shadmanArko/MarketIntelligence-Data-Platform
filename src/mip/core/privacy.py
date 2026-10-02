"""Personal data minimised: reviewer / commenter identities become salted hashes before they reach raw."""

import hashlib
import hmac
from typing import Any

from mip.settings import settings


def pseudonym(value: Any, namespace: str = "") -> str | None:
    if value is None or value == "":
        return None
    salt = settings().mip_hash_salt.encode()
    if not salt:
        raise RuntimeError("MIP_HASH_SALT is not set; refusing to store personal identifiers")
    return "h:" + hmac.new(salt, f"{namespace}:{value}".encode(), hashlib.sha256).hexdigest()[:32]


def hash_fields(obj: dict[str, Any], fields: tuple[str, ...], namespace: str) -> dict[str, Any]:
    """Replace identity fields in place with pseudonyms; keeps the key so the shape is unchanged."""
    for f in fields:
        if f in obj and obj[f] is not None:
            obj[f] = pseudonym(obj[f], namespace)
    return obj
