"""Data acquisition (Phase 2): the collector framework and the collectors.

docs/COLLECTORS.md is the contract. The framework is :mod:`.base` (interfaces),
:mod:`.sources` (``sources.yaml``), :mod:`.urls`, :mod:`.robots` and :mod:`.client` (the
polite HTTP client), :mod:`.replay` (fixture replay), :mod:`.store` (raw snapshots),
:mod:`.registry` (collector modules) and :mod:`.runs` (run lifecycle). Every collector is a
module ``mdt.collectors.<name>`` that exposes ``COLLECTOR``.
"""
