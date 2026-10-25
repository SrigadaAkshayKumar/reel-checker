from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..core.config import Settings
from ..core.http import Http
from ..db.store import Store
from .llm import Gemini
from .models import Claim


@dataclass
class Context:
    settings: Settings
    http: Http
    store: Store
    llm: Gemini
    reference: date  # when the reel was posted (or today): what "now" means for the claim


class SkipCheck(Exception):
    """A check could not run (no key, quota spent). Carries the check status."""

    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def claim_cutoff(ctx: Context, claim: Claim) -> date:
    """The date the reel claims the footage is from; the posting date when it
    gives none. Footage published before this (minus a tolerance) predates the claim."""
    if claim.claimed_date:
        try:
            return min(date.fromisoformat(claim.claimed_date), ctx.reference)
        except ValueError:
            pass
    return ctx.reference
