---
entity_type: district
district_id: ""                # UPPER_SNAKE_CASE of the district name, e.g. "ARARIA"
name: ""
state: "Bihar"
source:
  source_id: ""
  source_url: ""
  fetch_date: null
  verification_status: ""
last_compiled: null
---

<!-- One district = one note. Its region/category classification(s) live in
     separate district_classification notes (one per scheme that classifies
     it), NOT on this note -- a district can be classified differently by
     different schemes, and that disagreement must stay visible rather than
     being collapsed onto a single field. -->
