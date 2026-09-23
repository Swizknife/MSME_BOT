"""Google Open Knowledge Format v0.2 -- the spec, as code.

OKF is an open specification published by Google Cloud (announced 13 June
2026 at v0.1; this module targets **v0.2**) for representing knowledge as
plain Markdown files with YAML frontmatter in a directory tree:

    https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

This module models the *spec's* vocabulary and nothing else. It deliberately
knows nothing about MSME policy, incentives or districts -- that is
``schemas.py``'s job. A vault note is validated twice, against two
independent contracts:

    OKFDocument.model_validate(note.frontmatter)   # is it valid OKF?
    ENTITY_MODELS[t].model_validate(payload)       # is it a valid Incentive?

Two validations, two error messages, neither able to mask the other.

A note on the naming collision this module exists to correct: an earlier
build of this project coined "OKF -- Open Knowledge Framework" as a name for
its own structured-fact layer, independently and without knowing Google's
Open Knowledge *Format* existed. The two turned out to describe almost the
same thing (Markdown + YAML frontmatter + cross-links + provenance), so the
project now conforms to the real specification rather than to a lookalike.

## The one rule that shapes this whole module

The spec says a consumer **MUST NOT** reject a document for carrying
frontmatter keys it does not recognise, and **MUST** preserve them. That is
why every model here sets ``extra="allow"``. It is not laxness: it is the
mechanism by which this project's ~40 domain fields (``incentive_id``,
``category_rates``, ``clause_ref`` ...) ride along inside a document that is
still fully conformant and still portable to any other OKF consumer.

Conformance, per the spec, is a low bar deliberately:

  1. every non-reserved ``.md`` file has parseable YAML frontmatter, and
  2. that frontmatter has a non-empty ``type``.

``verify_okf.py`` checks that, plus the stricter house rules this project
adds on top (every ``sources[]`` entry resolves, every footnote label
matches a ``sources[].id``, no legacy ``[[wikilink]]`` survives).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The spec version this module implements.
OKF_VERSION = "0.2"

# Filenames the spec reserves. They are not concept documents and must not be
# validated as such: `index.md` is a directory listing for progressive
# disclosure, `log.md` is a chronological change history.
RESERVED_FILENAMES = frozenset({"index.md", "log.md"})

# Frontmatter keys the spec defines. Everything else in a document's
# frontmatter is a producer extension, which this project uses for its domain
# fields. `frontmatter.py` splits a note along exactly this line.
OKF_OWNED_KEYS = frozenset({
    "type", "title", "description", "resource", "tags",
    "generated", "verified", "status", "stale_after",
    "sources", "usage_window", "okf_version",
})


class OKFActor(BaseModel):
    """An entry in ``generated:`` or ``verified:``.

    ``by`` follows the spec's actor convention:

        human:<id>            a person          -> human-reviewed
        process:<id>          an automated job  -> machine-confirmed
        <producer>/<version>  an agent or tool  -> machine-confirmed

    The distinction is not cosmetic. It is the sole input to ``trust_tier()``,
    and this project surfaces that tier in the UI next to every fact, so
    claiming ``human:`` for something only a script checked would overstate
    the evidence to the person reading the answer.
    """

    model_config = ConfigDict(extra="allow")

    by: str = Field(..., min_length=1)
    at: Optional[datetime] = None


class OKFSource(BaseModel):
    """An entry in the ``sources:`` provenance list.

    ``resource`` is the only field the spec requires. Everything else is
    optional, and this project attaches its richer provenance (fetch method,
    extraction method, page range, checksum) as extension keys on the same
    entry rather than inventing a parallel structure.

    ``id`` is load-bearing beyond identification: the spec keys per-claim
    markdown footnotes to it, so ``some claim.[^bihar-msme-2026]`` joins to
    the matching ``sources[].id``. That is how a single sentence in a note
    body carries its own attribution, which is exactly what a
    citation-grounded bot needs.
    """

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    resource: str = Field(..., min_length=1)
    title: Optional[str] = None
    author: Optional[str] = None
    usage_count: Optional[int] = None
    last_modified: Optional[str] = None


class OKFDocument(BaseModel):
    """The spec-defined view of one concept document's frontmatter.

    Validating a note against this answers only "is this valid OKF?". It says
    nothing about whether the note is a coherent Incentive -- deliberately,
    because a note can be perfectly conformant OKF and still be nonsense as
    policy data, and the two failures deserve separate error messages.
    """

    model_config = ConfigDict(extra="allow")

    # The only field the spec requires.
    type: str = Field(..., min_length=1)

    # Recommended.
    title: Optional[str] = None
    description: Optional[str] = None
    resource: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    # Trust and lifecycle.
    generated: Optional[OKFActor] = None
    verified: list[OKFActor] = Field(default_factory=list)
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: Optional[datetime] = None

    # Provenance.
    sources: list[OKFSource] = Field(default_factory=list)
    usage_window: Optional[dict[str, Any]] = None

    @field_validator("verified", mode="before")
    @classmethod
    def _coerce_single_verified(cls, v: Any) -> Any:
        """The spec allows ``verified:`` to be one mapping instead of a list.

        It also says consumers must treat that single mapping as a
        one-element list, so normalising here means no caller downstream has
        to remember which of the two shapes it is looking at.
        """
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    def extensions(self) -> dict[str, Any]:
        """Frontmatter keys that are not part of the spec.

        For this project that is the entire domain payload.
        """
        return {
            k: v
            for k, v in (self.model_extra or {}).items()
            if k not in OKF_OWNED_KEYS
        }


TrustTier = Literal["unverified", "machine-confirmed", "human-reviewed"]


def trust_tier(doc: OKFDocument) -> TrustTier:
    """Derive the document's trust tier, per the spec's rule.

        no ``verified`` key               -> unverified
        verified only by non-human actors -> machine-confirmed
        verified by any ``human:<id>``    -> human-reviewed

    This is the honest-reporting mechanism, and it cuts both ways. A note
    whose only verification is ``process:verify_policy_data`` is
    machine-confirmed, not human-reviewed -- even though a script checking a
    figure against the source PDF is genuinely strong evidence. Saying
    "machine-confirmed" where that is what happened is the point.
    """
    if not doc.verified:
        return "unverified"
    if any(actor.by.startswith("human:") for actor in doc.verified):
        return "human-reviewed"
    return "machine-confirmed"


def is_reserved(filename: str) -> bool:
    """True for ``index.md`` / ``log.md`` at any depth in the bundle."""
    return filename in RESERVED_FILENAMES


def concept_id(path_relative_to_bundle: str) -> str:
    """The spec's concept ID: the bundle-relative path with ``.md`` removed.

    ``incentives/capital-subsidy.md`` -> ``incentives/capital-subsidy``

    Always forward slashes, because a concept ID appears inside markdown
    links and must not change shape on Windows.
    """
    p = path_relative_to_bundle.replace("\\", "/")
    return p[:-3] if p.endswith(".md") else p
