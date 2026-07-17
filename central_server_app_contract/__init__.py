"""Central Server App Foundation — the CONTER supervisor contract.

Reduced scope (v0.2.0): this package is no longer a full web chassis.
The generic chassis (auth UI, design system, settings, wiki, i18n)
lives in ``control_foundation``; what remains here is exactly the
protocol between the Central server and its managed apps — the part
that only makes sense inside a CONTER plant:

- contract.health     — /health /version /icon /shutdown blueprint factory
- contract.cli        — argparse helpers for --headless/--prefix/--info/…
- contract.data_paths — CONTER_DATA_DIR resolver
- version             — bundled-version-file + pyproject reader + uptime
- auth                — RemoteUserStore against the Central's
                        /api/auth/v1 + remote_user_store_from_env
                        + role taxonomy (VALID_ROLES, can_publish)
- sso                 — conter_sso signed cookie: issuer (Central) and
                        gate (subapps), sliding expiry, global logout

The last full-chassis release is tagged ``v0.1.0``; apps that have not
yet migrated to ``control_foundation`` must pin that tag.
"""

__version__ = "0.2.0"
