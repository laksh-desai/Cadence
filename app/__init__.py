"""Cadence — local, offline clinical note drafting for a physical therapy practice."""

#: The single source of truth for the shipped version. Bumped by `scripts/release.py`, which
#: refuses to build if this does not match the git tag it is cutting.
#:
#: This is stamped onto every note that is saved (`notes.app_version`), which is the reason it
#: exists at all. Cadence's generation rules change what notes SAY — a prompt fix, a new
#: postprocess backstop, a template edit — so "which version wrote this note?" is a clinical
#: question, not a packaging one. Without it, a note written before a rule changed is
#: indistinguishable from one written after, and there is no way to answer "did that fix reach
#: the notes I already signed?".
__version__ = "1.0.0"


def version() -> str:
    return __version__
