"""Vault I/O: reading and writing OKF Markdown notes.

A vault note is YAML frontmatter delimited by `---` lines, followed by a
free-text Markdown body:

    ---
    entity_type: incentive
    incentive_id: ...
    ---

    ## Heading

    Prose, with [[WIKILINKS]] to other notes.

This module is deliberately dumb: it parses and serializes, and knows
nothing about what any particular entity means. Validation against the
entity schemas lives in compiler.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

REPO_ROOT = Path(__file__).resolve().parents[3]
VAULT_DIR = REPO_ROOT / "data" / "okf_vault"
REFERENCE_DIR = VAULT_DIR / "_reference"
COMPILED_DIR = REPO_ROOT / "data" / "okf_compiled"

# Folders holding authored entity notes, in the order the compiler walks
# them. `_templates` and `_reference` are deliberately excluded: templates
# are blank skeletons and reference sets are validation inputs, not facts.
ENTITY_FOLDERS = {
    "scheme": "01_schemes",
    "incentive": "02_incentives",
    "eligibility_rule": "03_eligibility_rules",
    "authority": "04_authorities",
    "district": "05_districts",
    "district_classification": "05_districts",
    "sector": "06_sectors",
    "glossary_term": "07_glossary",
    "ambiguity_flag": "08_ambiguities",
    "act": "09_acts",
}

# The frontmatter field holding each entity type's own identifier.
#
# Lives here rather than in compiler.py because links.py needs it too, and
# the compiler imports links -- so keeping it in the compiler would make the
# two modules circular. vault.py is the dumb, dependency-free base both sit
# on top of.
ID_FIELD = {
    "scheme": "scheme_id",
    "incentive": "incentive_id",
    "eligibility_rule": "rule_id",
    "authority": "authority_id",
    "district": "district_id",
    "district_classification": "classification_id",
    "sector": "sector_id",
    "glossary_term": "term_id",
    "ambiguity_flag": "id",
    "act": "act_id",
}


@dataclass
class VaultNote:
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def entity_type(self) -> str:
        return str(self.frontmatter.get("entity_type", "")).strip()

    def wikilinks(self) -> list[str]:
        """Every [[TARGET]] in the body and in list-valued frontmatter fields."""
        found = list(WIKILINK_RE.findall(self.body))
        for value in self.frontmatter.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        found.extend(WIKILINK_RE.findall(item))
        # De-duplicate, preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for link in found:
            if link not in seen:
                seen.add(link)
                out.append(link)
        return out


def parse_note(path: Path) -> VaultNote:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(
            f"{path}: no YAML frontmatter found. A vault note must start with a "
            f"'---' line, contain YAML, and close with another '---' line."
        )
    front_raw, body = match.group(1), match.group(2)
    try:
        frontmatter = yaml.safe_load(front_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: frontmatter is not valid YAML -- {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{path}: frontmatter must be a YAML mapping, got {type(frontmatter).__name__}")
    return VaultNote(path=path, frontmatter=frontmatter, body=body.strip())


def iter_notes(vault_dir: Path = VAULT_DIR) -> list[VaultNote]:
    """Every authored note in the vault, skipping templates and reference sets."""
    notes: list[VaultNote] = []
    for md in sorted(vault_dir.rglob("*.md")):
        rel_parts = md.relative_to(vault_dir).parts
        if rel_parts[0] in ("_templates", "_reference"):
            continue
        if md.name == "README.md":
            continue
        notes.append(parse_note(md))
    return notes


def write_note(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100000,   # never wrap: a wrapped rate_text is a changed rate_text
    ).rstrip()
    # newline="\n" is load-bearing, not style. Path.write_text() defaults to
    # newline=None, which translates "\n" to os.linesep -- so this function
    # emitted CRLF on Windows and LF on Linux for identical input. That makes
    # a note's bytes a function of the machine that wrote it, and
    # app.okf.verify_migration proves the migration lost nothing by asserting
    # a regenerated note is BYTE-IDENTICAL to the one on disk. Writing LF
    # unconditionally keeps that check about content, and matches the
    # `eol=lf` policy in .gitattributes.
    path.write_text(
        f"---\n{front}\n---\n\n{body.strip()}\n", encoding="utf-8", newline="\n"
    )


def load_reference_set(name: str) -> dict[str, Any]:
    """Load a reference set (a closed universe used by the completeness pass)."""
    path = REFERENCE_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Reference set not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def normalize_member(name: str, aliases: dict[str, list[str]]) -> str:
    """Map a source's spelling of a reference-set member to the canonical one.

    Government sources spell several Bihar districts inconsistently
    (Purnea/Purnia, Kaimur/Bhabua). Without this, a completeness check
    reports false gaps at multi-source scale.
    """
    for canonical, variants in (aliases or {}).items():
        if name == canonical or name in (variants or []):
            return canonical
    return name
