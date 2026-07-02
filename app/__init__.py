"""LIMBO — public-signal intelligence console.

A self-hosted OSINT suite that works ONLY with public data / official public
APIs. Everything here is organised so you can read it top-to-bottom and learn:
`core/` holds the tiny framework (base module, detector, orchestrator, entity
graph, cache); `modules/` holds one file per capability; `main.py` wires it all
into a FastAPI app that also serves the mobile+desktop web console.
"""

__version__ = "1.0.0"
__appname__ = "LIMBO"
