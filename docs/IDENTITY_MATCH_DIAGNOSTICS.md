# Explainable title matching

The unified identity worker now records a matching trace for each investigated Autobrr notification. In Jobs, select **Matching details** to see parsed title queries and episode, AniDB exact title matches, TVDB candidate counts, scored TVDB names, threshold pass/fail, explicit TVDB↔AniDB cross-reference results, and the episode evidence outcome.

The setting `identity.match_threshold_pct` defaults to **90** and accepts an integer **50–100**. It filters the TVDB *name* candidates by normalized character similarity; it does not turn an AniDB public catalog exact-title lookup into fuzzy matching. Changing it affects the next investigation; past stored traces retain the threshold used at the time. It does not automatically re-run old NEEDS_REVIEW entries. Existing settings files use the default until migrated.

Scoring is diagnostic/candidate filtering only. A high score is not identity proof. A download still requires the explicit provider IDs, verified exact AniDB episode mapping, unique TVDB aired episode and the existing acquisition gate. Errors and rejected results fall back to NEEDS_REVIEW with the existing NTFY mechanism. Provider outages follow the existing retry policy.

Worker journal example (illustrative, not an actual lab result):
```
identity notification=27 attempt=1 decision=NEEDS_REVIEW threshold=90 anidb_matches=1 tvdb_candidates=2 issues=NO_EXPLICIT_TVDB_ANIDB_CROSSREF,EXACT_IDENTITY_NOT_VERIFIED
identity notification=27 tvdb_candidate=123 score=84 threshold=90 result=BELOW_TITLE_THRESHOLD
identity notification=27 step=TVDB search details={"returned": 2, "threshold_pct": 90}
```

The app never writes API keys or provider bearer tokens to diagnostics. Logs are bounded to 10 candidates and 12 steps per investigation. The dashboard's read-only trace is available only to an authenticated administrator. Source data for old releases may lack score details because it was recorded before this upgrade.


## Multilingual TVDB candidate evidence

TVDB search candidates now retain bounded provider-supplied primary, translated, original and alias titles. Unicode NFKC normalization retains non-Latin scripts but does not transliterate them. Each title-score diagnostic records the best release query and real provider title, their score and the configured threshold. The originating search query is never treated as candidate title evidence. An empty title set is reported as `NO_USABLE_CANDIDATE_TITLES`.

A passed title score does not verify an identity: the explicit TVDB/AniDB cross-reference, reviewed exact episode mapping, confirmed aired TVDB episode and acquisition approval remain mandatory. Similarity collisions require review when cross-references are ambiguous.
