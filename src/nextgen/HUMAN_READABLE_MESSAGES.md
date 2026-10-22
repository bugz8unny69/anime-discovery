# Human-readable diagnostic messages — mandatory NextGen policy

Every emitted operational marker or error MUST have a centrally registered,
nonblank, human-readable English message. A machine code alone is not an
operator explanation. This rule applies at every verbosity level, including
DEBUG and TRACE, and to normal progress/wait/success markers as well as failures.

This policy is a required part of implementing [the diagnostic contract](DIAGNOSTIC_CONTRACT.md).
It defines the rule now; journal rendering, event/status catalogs, translation
loading and coverage enforcement are not implemented by this documentation PR.
The reason catalog in reasons.py already supplies English message and action
fields. Legacy is reference material, not a runtime dependency to import.

## Required behavior

1. Register each event, reason/error and displayed state before emitting it.
   Give each entry a stable code, precise meaning, default English message,
   stable message key, and owner. Errors/reasons also have a separate suggested
   action and action key where an operator action is meaningful.
2. Every operational failure crossing a component boundary must map to a
   registered reason, including a registered unexpected-failure fallback.
   Preserve its event code, reason code and correlation separately. Internal
   programmer exceptions need not each get a unique code; the catch boundary
   must classify them. Never derive a code from str(exception).
3. Journal output MUST include the stable code AND its human-readable message.
   A failure entry includes both the event message and the reason message.
   Normal filtering still applies; this does not require emitting disabled
   TRACE/DEBUG messages. Structured technical facts remain separate fields.
4. Dashboard and CLI/M MUST use the same centrally owned messages and keys.
   Do not maintain a second explanation dictionary in JavaScript, hardcode
   component-specific translations, or replace underscores to invent prose.
5. Persist stable identifiers and approved, bounded typed facts. Do not persist
   English/localized prose as the authoritative reason, parse messages to make
   decisions, or change scheduler behavior according to a translation.
6. Keep unknown historical entries readable through registered generic fallback
   messages. Missing current catalog coverage is a development defect, not
   permission to emit a new bare code. A runtime defensive fallback must remain
   safe and visible instead of crashing the worker or losing accepted work.
7. Each PR introducing a marker/error/state MUST include its central English
   entry, message key, documentation and offline coverage cases in that PR.
   Include tests now but do not execute them or trigger CI under current policy.

"Marker" means a named operational observation: lifecycle events, reasons,
waiting/review outcomes, checkpoints and display states. Correlation IDs,
numeric measurements and field names are structured facts, not separate
sentences that each require their own error code.

## Separate what happened, why, and current state

These are separate catalog namespaces even when their codes have identical
spelling. State labels also need readable text, but they are not errors.

| Namespace | Example code | Default English message | Stable message key |
| --- | --- | --- | --- |
| event | ACCEPTED | Incoming event accepted. | event.ACCEPTED.message |
| event | CLAIMED | Job processing started. | event.CLAIMED.message |
| event | RETRY_SCHEDULED | Another processing attempt has been scheduled. | event.RETRY_SCHEDULED.message |
| event | NEEDS_REVIEW | Processing has stopped for review. | event.NEEDS_REVIEW.message |
| reason | PROVIDER_UNAVAILABLE | An information provider is temporarily unavailable. | reason.PROVIDER_UNAVAILABLE.message |
| reason | JOB_LEASE_EXPIRED | Processing was interrupted. | reason.JOB_LEASE_EXPIRED.message |
| state.job | NEEDS_REVIEW | Needs review | state.job.NEEDS_REVIEW.label |
| state.job | RETRY_WAIT | Waiting for another attempt | state.job.RETRY_WAIT.label |

The event examples are required copy for the proposed lifecycle catalog, not
a claim that it already exists in executable code. The complete initial event
and state copy is specified in DIAGNOSTIC_CONTRACT.md. Existing reason English
copy remains owned by reasons.py; do not duplicate it into an independently
maintained runtime dictionary.

Illustrative journal entry (not a captured runtime log):

```text
event_code=RETRY_SCHEDULED message="Another processing attempt has been scheduled." reason_code=PROVIDER_UNAVAILABLE reason_message="An information provider is temporarily unavailable." trace_id=AD-42 job_id=73 attempt=2
```

A provider-unavailable reason by itself must not claim a retry will happen.
Only RETRY_SCHEDULED says a retry was actually scheduled. The same separation
applies to review, completion and external actions.

## Translation-ready catalog contract

Use keys derived from the immutable namespace and code, never from English
wording: event.<CODE>.message, reason.<CODE>.message, reason.<CODE>.action,
and state.<entity>.<CODE>.label. These keys are translation identifiers,
not additional workflow codes. Preserve them when copy changes; never recycle
a code/key to mean something else.

English is required and is the default journal language. A future configured
journal locale or viewer locale can select translations through the shared
renderer. An unsupported locale or missing translation falls back to English.
Changing the viewer locale must not rewrite history or affect retry behavior.
Missing English entries fail catalog validation before release; defensive
runtime fallback covers unknown historical data/version mismatches.

For this initial foundation, use complete static sentences with no placeholders.
Keep IDs, attempt counts and times as separate typed facts. Future variable
messages require explicitly named and typed, allowlisted parameters, bounds,
matching placeholder sets in every locale, and proper plural forms; do not
assemble translated sentences from fragments. Resolve each sentence separately
and let the presentation layer arrange them; do not build English-only
"event + because + reason" strings.

The future management API should return the machine identifiers and resolved
message/action text (and message keys if the client needs them), rather than
requiring the browser to interpret exceptions or invent meanings.
Translation catalogs must not permit executable expressions or HTML rendering.

## Security and historical compatibility

Messages and actions are trusted static catalog text. They must not contain
raw request bodies, provider payloads, release names, credentials, tracker or
magnet URLs, file paths, lease tokens, or str(exception). Regex redaction of
arbitrary text is not a substitute for selecting safe content.

Render dashboard/CLI text through the appropriate escaping/output policy.
Only show syntactically bounded historical codes as secondary diagnostic IDs;
malformed identifiers receive UNKNOWN without echoing their raw value.
Unknown syntactically valid identifiers still cannot be assumed secret-free;
codes must originate from trusted application metadata.

Generic fallback copy must distinguish event, reason and state, without
pretending to know whether something succeeded, failed, or needs review:

| Fallback | Default English text |
| --- | --- |
| event.UNKNOWN.message | Additional processing activity was recorded. |
| reason.UNKNOWN.message | Additional processing information is available. |
| reason.UNKNOWN.action | Review the job history. |
| state.UNKNOWN.label | Unknown status |

Preserve the original stored code for historical investigation, subject to
safe display. Do not rewrite old rows to the fallback identifier.
Keep retired catalog entries readable. If a translation is absent, show English;
if the code itself is unknown, show the generic message plus a safe code.
Additional structured underlying causes, such as cause_reason_code, must also
be resolved through the same catalog when shown to humans.

## Legacy inspection: useful precedent and gaps

Reviewed at commit 8fc7eb45b017c15f2921c0260e3caee4bf5885b4.
This is a targeted source review, not a complete inventory or legacy rewrite.

| Source | Observed behavior | NextGen requirement |
| --- | --- | --- |
| src/legacy/anime_review_messages.py, REVIEW_DESCRIPTIONS / describe_review | Central Python mappings for 18 reasons, e.g. EPISODE_SIZE_EXCEEDED → "Episode exceeds the configured download size limit."; generic unknown/LOOKUP fallbacks | Preserve the central code-to-message approach; require coverage for every newly emitted marker, not a subset |
| src/legacy/anime_dashboard_pages.py, traceIssueExplanation / openTrace | Separate JavaScript explanations; some labels are made by replacing underscores; candidate/cross-reference reasons can be shown as raw codes | One shared catalog; readable labels and reasons in basic and advanced views |
| src/legacy/anime_diagnostics.py, event | Emits event=<name> plus allowlisted technical facts, without central message resolution | Resolve a human sentence for every journal marker |
| src/legacy/anime_qb_manifest_intake.py, submit_poll_pause | Logs codes such as TORRENT_NOT_VISIBLE and METADATA_NOT_READY without accompanying descriptive sentences | Every wait/rejection/success reason has explicit readable meaning |
| src/legacy/anime_async_daemon.py, run_workers | Some reasons come from exception class names or transformed exception text | Explicit registered reason at the catch boundary |
| src/legacy/anime_acquisition_handler.py, execute | Several returns set only NEEDS_REVIEW without a distinct explanatory reason | Every failure/review outcome explains why; status alone is insufficient |

Illustrative English explanations for markers actually found in the legacy
sources (reference examples, NOT new NextGen acquisition registrations):

| Legacy marker/code | Human-readable explanation |
| --- | --- |
| TORRENT_NOT_VISIBLE | The torrent is not yet visible in the download client. |
| METADATA_NOT_READY | The torrent file list is not available yet. |
| OWNERSHIP_UNPROVEN | The application could not verify that it owns this torrent. |
| MANIFEST_CHANGED | The torrent file list changed after it was recorded. |
| FILE_LIST_VERIFIED | The torrent file list has been verified. |
| FIRST_EPISODE_NOT_YET_STAGED | Waiting for the first episode to finish staging. |
| SKIPPED_DUPLICATE | This episode was skipped because it is already being handled or has been staged. |
| DUAL_AUDIO_REQUIREMENTS_NOT_MET | The downloaded video does not have the required Japanese and English audio tracks. |

A future TORRENT_UNAVAILABLE reason, if its handler defines that exact meaning,
might say "The torrent is currently unavailable." This was the user's example,
not a code verified in the inspected files. Prefer precise existing distinctions
such as client visibility versus missing metadata; do not collapse them into
one vague error or register future acquisition behavior prematurely.

## Required offline acceptance cases for implementation

- Every registered event, reason, display state and newly introduced checkpoint
  has nonblank English copy, a unique namespaced key and documented meaning.
  No missing coverage is hidden by the generic fallback.
- Each registered emitted event/reason pair produces both stable identifiers
  and readable messages in enabled journal output.
- Dashboard/CLI presentation and journal resolve the same English catalog
  entries; no independent client mapping is required.
- An alternate-locale fixture resolves the same keys; missing translations and
  unsupported locales fall back to English without changing stored identifiers.
- Unknown historical codes use readable generic text; malicious or malformed
  codes are not echoed; translations cannot inject markup or control sequences.
- Exception messages, tokens, URLs and arbitrary payload text never enter
  public messages, including fallback paths and translated variants.
- Static-message rendering cannot alter scheduler state, retry decisions,
  transaction outcomes or canonical history.

These are test requirements for the upcoming implementation. This policy PR
adds documentation only; it does not claim those executable tests exist or pass.
