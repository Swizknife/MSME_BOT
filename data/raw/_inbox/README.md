# Manual download inbox

Drop hand-downloaded source files here. Nothing in this folder is read by the
bot directly — `python -m app.acquisition.register_manual_fetch` moves each
file into its real home at `data/raw/<SOURCE_ID>/<date>.<ext>`, computes the
sha256, and writes the same `.meta.json` and `_latest.json` an automated fetch
would have produced. From that point on nothing downstream can tell whether a
file arrived by scraper, by agent, or by a person in a browser — which is the
point.

**Name each file exactly `<SOURCE_ID>.<ext>`** using the IDs below. The
extension should match what the portal actually gave you (`.pdf`, `.html`).
Don't rename the content or re-save it through another program — the checksum
is meant to match the bytes the government portal served.

## Wanted, in priority order

| Save as | What to get | Where |
|---|---|---|
| `BIIPP_DISTRICT_CATEGORISATION.pdf` | **Highest value.** The annexure listing which districts are Region A and which are Region B. | [state.bihar.gov.in/industries](https://state.bihar.gov.in/industries/) → Policies |
| `BIIPP_POLICY.pdf` | Bihar Industrial Investment Promotion Policy, full document | same portal |
| `BIHAR_MSME_POLICY_2026.pdf` | The **notified** MSME Policy 2026, if one has been published. If only the draft exists, say so — "still not notified as of `<date>`" is itself a fact worth recording. | same portal |
| `BIHAR_STARTUP_POLICY.pdf` | Bihar Startup Policy (2022, or 2026 if notified) | [startup.bihar.gov.in](https://startup.bihar.gov.in/) |
| `UDYAM_REGISTRATION_FRAMEWORK.pdf` | The registration framework / classification notification | [udyamregistration.gov.in](https://udyamregistration.gov.in/Government-India/Ministry-MSME-registration.htm) |
| `MSMED_ACT_2006.pdf` | Only if you can find a copy **with a text layer**. The one at dcmsme.gov.in is a scanned image, and indiacode.nic.in returns 403. | legislative.gov.in or msme.gov.in |

## Why these need a person

All six are government portals that refuse scripted access. That refusal is
theirs to make, and the acquisition pipeline is built to respect it rather than
work around it: `compliance.py` will not issue an automated request for a
source whose terms nobody has reviewed. A person opening a page in a browser is
not automated access, so a manual download is the correct path here, not a
workaround.

## Why BIIPP District Categorisation is first

It is the **second** source for how Bihar districts are classified. With only
one source, a disagreement is invisible — there is nothing to disagree with.
With two, the compiler's contradiction pass can fire for the first time, which
is what turns `AMB-01` from a documented ambiguity into a resolvable one, and
what lets the bot say "these two documents disagree" instead of silently
picking whichever chunk happened to rank higher.
