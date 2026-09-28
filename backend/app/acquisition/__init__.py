"""Dataset acquisition package (Phase 2 of the OKF+RAG rebuild -- not built yet).

Will eventually hold:
  - fetchers/html_scrape.py, fetchers/pdf_download.py, fetchers/api.py
    one module per fetch_strategy in config/sources.yaml, each returning a
    common FetchResult contract (source_id, fetched_at, raw_path, checksum, status).
  - run_acquisition.py   orchestrates the source registry: dispatches each
                         source to its fetcher, and on a blocked-fetch
                         signature (403/429/CAPTCHA marker) flips that
                         source to manual_pending and prints its
                         manual_fallback_instructions instead of failing
                         the whole batch.

                         MUST enforce the compliance gate documented at the
                         top of config/sources.yaml before any automated
                         fetch: refuse (skip and report, do not fetch) any
                         source whose fetch_strategy is html_scrape,
                         pdf_download or api while compliance_checked is
                         not true or robots_txt_status is not 'allowed'.
                         The manual strategy is exempt. As of Phase 0 every
                         registered source fails this gate by default, which
                         is intentional -- clearing it is a per-source human
                         review, not a code change.
  - register_manual_fetch.py   stamps a manually-downloaded file (already
                         placed at data/raw/<source_id>/<fetch_date>.*) into
                         the registry exactly as an automated fetch would,
                         so downstream steps never branch on acquisition
                         method.

See config/sources.yaml for the source registry and
docs/OKF_RAG_IMPLEMENTATION.md §6 for the acquisition pipeline design.
"""
