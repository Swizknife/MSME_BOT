---
entity_type: sector
sector_id: ""                  # UPPER-SNAKE, unique, e.g. "FOOD_PROCESSING"
name: ""
classification_type: ""          # high_priority | priority | emerging | negative_list | zed_target | odop
scheme_id: ""                     # which scheme's annexure/list this classification comes from
nic_codes: []                       # National Industrial Classification codes, if stated
source:
  source_id: ""
  source_url: ""
  fetch_date: null
  page_or_section_ref: ""
  verification_status: ""
last_compiled: null
---

<!-- A sector can have multiple sector notes under different scheme_id /
     classification_type combinations (e.g. "high priority" under the Bihar
     MSME Policy and separately "ODOP product" under the ODOP scheme) --
     these are not duplicates, they are different schemes' independent
     classifications of the same real-world sector. -->
