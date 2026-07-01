"""Capability modules. One BaseModule subclass = one capability, auto-discovered.

Grouped by domain into a few files for readability:
  social.py   — username presence + public social/messaging profiles
  identity.py — email/self exposure (public breach NAMES only, never contents)
  infra.py    — domains, IPs, DNS, TLS, ASN, hosting, threat context
  image.py    — EXIF/GPS, forensics and geolocation aids
  intel.py    — dorks, decoders, lookups and misc utilities
"""
