"""AA Impact Inc. — upstream certificate issuance package.

This package is the *upstream* half of the certificate system. It takes
participant details, mints a unique certificate ID, computes the integrity
hash the public verifier recomputes, renders a certificate PDF, uploads it to
Supabase Storage, and writes the system-of-record row into the
``public.certificates`` table.

The *downstream* half (the public `validate-certificate` / `verify-certificate`
Supabase Edge Functions) is already deployed. The single most important
contract between the two halves lives in :mod:`certissuer.hashing` — the hash
payload must stay byte-for-byte identical on both sides.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
