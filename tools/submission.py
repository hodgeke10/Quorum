"""Submission details that must appear in BOTH deliverables.

Canvas takes files or a URL, not both, so the repository link has to travel
inside report.html and slides.html. The professor's instructions are explicit:
if the repo is not in both files it cannot be cloned, and it cannot be graded.

Set it once here; `build_report.py` and `build_slides.py` both read it, so the
two documents cannot disagree.
"""

from __future__ import annotations

REPO_URL = "https://github.com/hodgeke10/quorum"

# Set True if the repo is private. The professor must be told, in both files,
# and `zlisto` has to be added as a collaborator.
REPO_PRIVATE = False

PLACEHOLDER = "REPO_URL_HERE"


def is_placeholder() -> bool:
    return PLACEHOLDER in REPO_URL


def warn_if_placeholder(document: str) -> None:
    """Shout on the way past rather than let a placeholder reach Canvas."""
    if is_placeholder():
        print(f"  !! {document} still says {PLACEHOLDER} — set REPO_URL in "
              f"tools/submission.py before submitting")


def visibility_note() -> str:
    """One sentence about access, for the reader."""
    if REPO_PRIVATE:
        return ("This repository is <strong>private</strong>; the GitHub user "
                "<code>zlisto</code> has been added as a collaborator.")
    return "The repository is public."


def visibility_note_plain() -> str:
    if REPO_PRIVATE:
        return "Private repo — zlisto added as a collaborator."
    return "Public repository."
