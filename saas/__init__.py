"""Cadence SaaS fork skeleton.

Separate package from the live local app (`app/`) — see docs/saas-migration/. The local and
hosted builds have opposite security models ("single trusted machine" vs "hostile multi-tenant
internet"), so per the migration plan's "fork, don't mutate" stance the SaaS is built here rather
than by mutating the working app. What's real vs. stubbed is documented in saas/README.md.
"""
