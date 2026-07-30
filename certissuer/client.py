"""Supabase service-role client factory.

Issuance writes to the ``certificates`` table (no public INSERT policy) and to
the private ``certificates`` storage bucket, so it requires the **service-role
key**. That key bypasses RLS and must never be committed or logged — it is read
from the environment only.
"""

from __future__ import annotations

import os

from supabase import Client, create_client

_URL_ENV = "SUPABASE_URL"
_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"


def get_service_client() -> Client:
    """Create a Supabase client authenticated with the service-role key.

    Raises a clear error if either environment variable is missing.
    """
    url = os.environ.get(_URL_ENV)
    key = os.environ.get(_KEY_ENV)
    missing = [name for name, val in ((_URL_ENV, url), (_KEY_ENV, key)) if not val]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set them (see .env.example) before issuing certificates."
        )
    return create_client(url, key)
