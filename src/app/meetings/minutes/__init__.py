"""Post-meeting pipeline -- minutes generation and distribution.

MinutesGenerator extracts structured meeting minutes from transcripts
using instructor + litellm (Phase 4 pattern) with map-reduce for long
transcripts. MinutesDistributor handles internal storage and controlled
manual external sharing.
"""
