"""Typed outputs for every agent in Quorum.

Each agent returns a schema, never prose, so the orchestration in `agents.py`
can score and compare results in Python instead of re-parsing English.

Scores run **upward**: 10 means a traveler loves an option, 0 means it is not
for them. Quorum then picks the trip with the highest floor — the one that
works best for whoever it suits least. That is the same arithmetic as
minimising the worst case, stated the way a group would want to hear it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Candidate(BaseModel):
    """One option the Scout puts on the table."""

    dest_code: str = Field(description="Three-letter destination code from the snapshot.")
    start_date: str = Field(description="Trip start, YYYY-MM-DD, from an offered window.")
    tier: str = Field(default="mid", description="budget, mid, or upscale.")
    why: str = Field(description="One or two sentences: why this suits this group.")


class Shortlist(BaseModel):
    """The Scout's slate of options for the group to weigh."""

    candidates: list[Candidate] = Field(
        description="Three to five genuinely different options, not variations of one."
    )
    reasoning: str = Field(description="How the slate was chosen, in two sentences.")


class Verdict(BaseModel):
    """One traveler's advocate rating one option."""

    option_id: str
    fit: int = Field(
        ge=0, le=10,
        description="10 = this is my first choice, 0 = this one is not for me.",
    )
    would_join: bool = Field(description="Would this person happily come on this trip?")
    loves_most: str = Field(description="The best thing about this option for them.")
    one_wish: str = Field(
        description="The single thing they would change, said plainly and kindly."
    )


class AdvocateReport(BaseModel):
    """Everything one advocate says about the whole slate."""

    traveler: str
    verdicts: list[Verdict]
    bottom_line: str = Field(description="One warm, honest sentence in this traveler's voice.")


class Flex(BaseModel):
    """What one person is flexing on so the group can travel together."""

    traveler: str
    flexed_on: str = Field(description="Concretely what they are being flexible about.")
    the_numbers: str = Field(description="The size of the ask, in points or dollars.")


class Decision(BaseModel):
    """The Chair's final call."""

    winner_option_id: str
    headline: str = Field(description="One upbeat line a group chat would say yes to.")
    why_this_one: str = Field(
        description="Why this trip is right for this group, in its own terms "
                    "and with its own numbers. Never a comparison with another "
                    "option — the group is being told where they are going, not "
                    "shown a shortlist."
    )
    flexes: list[Flex] = Field(
        description="One entry per traveler who is flexing for the group. Be specific "
                    "and appreciative — these people made the trip possible."
    )
    good_to_know: list[str] = Field(
        default_factory=list,
        description="Practical heads-ups: weather, crowds, anyone close to their budget.",
    )
    confidence: str = Field(description="high, medium, or low, and one clause of why.")
