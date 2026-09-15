# v1.2 — Local-Only Digest Golden

Release date: 2026-09-16. Status: **GOLDEN**.

`PRODUCT_MODE=LOCAL_ONLY` · `READY_FOR_DAILY_USE=YES`

This release freezes the implementation at
`a9a9057e1870ddb028baf5de8c5e040b359e47b2`. The documentation commit containing
this file is the release closure reference, including the final Daily Use Runner
supplement. No additional version file or tag
is required. The repository's historical Pages demo README does not define the
v1.2 product workflow; this document defines the final v1.2 release scope.

## Release scope and Golden capabilities

- UTF-8 `URL|Title` input, strict Digest Registry and deterministic Planner.
- AI structured generation based only on digest identity, entry identity and Title.
- Deterministic Markdown Renderer, Digest Audit and static local HTML Preview.
- Mandatory manual review of each new generated Digest.
- Production Baseline v2 and Local-Only Safety checks.

Registry, Planner, Generator, Renderer, Audit, Preview, Local-Only Safety and
Production Baseline v2 passed release validation. Existing production articles
and runtime implementation were not changed during closure.

## Local-Only safety boundary

Generated Markdown and HTML belong under `output/digest/`, which is Git ignored.
Generated content must never enter staging, commits, pushes, Pages or automatic
publication. New Digests must not be written to `articles/`. Input files and
local evidence must not enter the release commit. Source and release-document
Git operations remain separate from generated-content operations.

The publication guard rejects simulated generated-content staging with
`LOCAL_ONLY_PUBLICATION_VIOLATION`. Ignore rules are an additional safeguard;
do not force-add ignored files. Legacy publication tools are outside this
release workflow and must not be used for v1.2 Digests.

Preview uses local files; no HTTP server, listener, tunnel or public URL check
is needed. A new Digest ends in `PENDING_MANUAL_REVIEW`, not a published state.
The software's Golden status does not grant publication approval to its output.

## 20-entry real Sandbox evidence

The existing real OpenAI run produced all 20 entries with no missing,
duplicate or unknown entries. Audit and deterministic rendering passed;
20 references preserved the exact Titles and URLs. No target URL was fetched.

Density revalidation artifacts, retained locally and excluded from Git:

- `output/digest/markdown/digest-8540f9b0-001.md`
- `output/digest/html/digest-8540f9b0-001.html`
- `output/digest/evidence/digest-local-sandbox-20-density-revalidation/`
- `output/digest/evidence/release-closure-acceleration/calibration-replay.json`

Markdown SHA256:
`2b1381f47efd50235146f2efe4c3a85d88578d854f5bdd09a92ef9ab91c11e1e`

HTML SHA256:
`bc79e86a9c03a92ae6bcccb69fa3d5c5c4ccf8c1bdfeba162ebabb916bbda613`

The earlier density Gate failed its then-current 80–150 recommendation.
That historical result is preserved. The user subsequently accepted the real
72–82-character, two-sentence style in a browser and authorized calibration
to 70–150. Replaying the same response under that contract passes 20/20 with
zero density warnings; no output was rewritten and no new AI request was made.

### Browser manual review

The user's explicit review and final release decision are the authority for
manual acceptance, superseding the older evidence's pending-user-review field:

| Criterion | Result |
| --- | --- |
| Article structure | PASS |
| Content density and readability | PASS |
| Link presentation | PASS |
| Category structure | PASS |
| Truthfulness style | PASS |
| Visual density | PASS |

Browser automation also confirmed 1 H1, 4 H2, 20 H3, 20 visible clickable
references, exact URL identity, and no visible front matter or raw/endraw tags.
Content review found no unsupported factual claims or mechanical opening
repetition. Automated checks do not replace manual semantic or visual review.

## Summary contract and truthfulness

- Recommended: **70–150 Unicode code points**, including punctuation.
- Hard range: **60–180 Unicode code points**; normally 2–3 natural sentences.
- 60–69 and 151–180 produce density warnings. Hard-range violations fail.
- Summaries are Title-based thematic introductions, not summaries of fetched pages.
- Do not imply reading the source, invent numerical facts, quotations, event
  outcomes or announcement details, or attribute unsupported claims to reporting.
- Titles are untrusted data, not instructions. AI does not control URL authority.
- Inspect warnings and content manually; do not mechanically pad text or retry
  merely to satisfy a style preference.

## Production Baseline v2

Schema: `2`. Algorithm: `git-content-sha256-manifest-v1`.
Production article count: **200**. Manifest entries: **200**.
`CONTENT_DRIFT=NO`.

Aggregate SHA256:
`4b00fd598a3a74c018e6e577575f79b959cda228a17ebfa447c85425a9fc7064`

The [baseline specification](production-baseline-v2.md) defines canonical
membership and hashing. Its remediation-era execution hold is historical;
this final closure decision supersedes that hold without changing the algorithm.
The unreproducible legacy aggregate is not this release's acceptance baseline.

## 50-entry external dependency decision

The user reported and manually confirmed credit balance **-0.03 USD**, and
explicitly classified the HTTP 429 as `EXTERNAL_API_CREDIT_UNAVAILABLE`.
This is user-confirmed billing evidence, not a new API or account inspection.
The original response body was not retained; HTTP status 429 was retained.

`IMPLEMENTATION_FAILURE=NO` · `DIGEST_CONTRACT_FAILURE=NO`
`LOCAL_ONLY_SAFETY_FAILURE=NO`

| 50-entry live RC component | Verified scope |
| --- | --- |
| Synthetic input | 50 entries, 50 unique URLs |
| Registry | 50 entries |
| Planner | 50 planned entries in one Digest |
| Live AI generation | DEFERRED_EXTERNAL_DEPENDENCY |
| Render of the live 50-entry response | NOT_VERIFIED |
| HTML of the live 50-entry response | NOT_VERIFIED |

Batch: `digest-local-release-candidate-50`.
Reason: `EXTERNAL_API_BILLING_UNAVAILABLE`.
Local records: `output/digest/evidence/digest-local-release-candidate-50/`.
The failed attempt made one request and no retry. Offline fixtures or other
local previews do not establish successful 50-entry live AI completion.

The user explicitly waived this live scale step as a v1.2 release blocker.
It remains a known unverified limit, not a claimed PASS. No further live
request, account switch, network switch or billing action is authorized by closure.

## Final offline regression

All checks passed without live generation or target URL requests:

| Suite | Tests passed |
| --- | ---: |
| Production Baseline | 14 |
| Digest Registry | 56 |
| Digest Planner | 62 |
| Digest Generator / Renderer | 52 |
| Digest Audit | 38 |
| Local Preview | 8 |
| Local-Only Safety | 6 |
| DIRECT | 99 |
| STRICT | 163 |
| Internal | 190 |
| Generation Adapter / Maintenance | 34 |
| ALL_TOOLS_TESTS | 712 |

Suite groupings overlap; counts are not additive. PY_COMPILE and COMPILEALL
passed. Offline test network attempts: 0. Secret scan: 0 matches.
Local closure verification records are under
`output/digest/evidence/final-release-closure/` and are not release-commit content.

## Daily Use Quick Start

The official entrypoint is `tools/digest_run.py`. It orchestrates the frozen
Registry, Planner, Generator, Renderer, Audit, Preview, Baseline and Safety.
No GUI, server or historical Sandbox script is required.

1. Start PowerShell in `E:\workspace\github-article-demo` and use the existing
   Python environment with the OpenAI SDK and HTTP client dependencies.
2. Save UTF-8 input to `input/daily-digest.txt`, one `URL|Title` pair per line.
   Provide Titles yourself; targets are never fetched. Duplicate URLs fail.
   Frozen planning requires at least 20 entries. The runner accepts only plans
   containing one Digest; multi-Digest runs are deferred.
3. Ensure the current process has `OPENAI_API_KEY` without printing its value.
   Confirm API Billing availability separately. The known billing condition is
   still unavailable; the runner stops on errors and never retries HTTP 429.
4. Run the official command:

   ```powershell
   python tools/digest_run.py --input input/daily-digest.txt
   ```

5. On success, open the absolute path printed after `HTML=` as a local file.
   Check all Titles, links, readable summaries and truthfulness. Each Digest
   ends in `PENDING_MANUAL_REVIEW`; no automatic publication follows.
6. Keep input, generated Markdown, HTML and evidence out of Git. Never use
   legacy publishing commands or force-add ignored output.

The runner derives a deterministic batch identity from parsed input identity,
not the clock or random data. The publication date is display metadata only.
The same input reuses the same destination and fails closed if a previous run
or output already occupies it. No historical output is deleted or overwritten.

For a deliberately separate run, supply a new explicit batch name:

```powershell
python tools/digest_run.py --input input/daily-digest.txt --batch-id daily-review-02
```

Names accept 1–80 ASCII letters, digits, hyphens and underscores, starting with
a letter or digit. Changing the name authorizes a separate invocation; it is
not automatic retry. Do not use it to repeat a failed API request until the
external cause has been resolved and another attempt is authorized.

Successful output includes `DIGEST_RUN_RESULT=PASS`, `ENTRIES`, `MARKDOWN`,
`HTML`, `AUDIT=PASS`, `CLICKABLE_HREF` and `FINAL_STATE=PENDING_MANUAL_REVIEW`.
Expected failures return a nonzero exit code and only `DIGEST_RUN_RESULT=FAIL`,
`STAGE`, `ERROR_CODE` and a safe `MESSAGE`, without exception bodies or traceback.
For `OPENAI_HTTP_429`, check API Billing / Rate Limit and stop.

Outputs remain under `output/digest/markdown/`, `output/digest/html/` and
`output/digest/evidence/`. After reserving a run, minimal evidence is written to
`output/digest/evidence/<batch-id>/run-result.json`, including identities, paths,
call count and status, without runtime credentials. Early input, baseline or
credential failures do not reserve output. Failed reserved runs retain evidence
and reservations; they are not silently reused. A partial preview from a failed
write is not a successful run: only exit code 0 and PASS authorize manual review.

The Runner supplement was validated with 30 offline Runner tests and 742 total
suite tests, plus a 50-entry Fake-client CLI smoke with exact 50/50 links.
This proves offline orchestration only, not 50-entry live AI completion. No real
OpenAI request was made for the Runner release. The frozen core is unchanged;
the documentation, Runner and Runner tests form its sole release supplement.

Accepted reference preview:
`E:\workspace\github-article-demo\output\digest\html\digest-8540f9b0-001.html`.

## Known limitations and deferred v1.3

Daily-use readiness refers to the released local workflow. New live AI generation
still requires external credit/service availability; the current billing
condition is not remedied by this release. The AI is Title-grounded and cannot
verify page facts. Manual review remains required for every new output.

The following are **DEFERRED_V1_3**, not further v1.2 development requirements:

- 50 Entry Live AI Scale Revalidation; 100 Entry Scale Validation.
- Multi-Digest Daily Runner, GUI, automatic Title extraction and target-page fetching.
- More templates, formats and complex categorization.
- Automatic publication and GitHub Pages.
- Performance micro-optimizations and noncritical refactoring.

Deferral is not future execution authorization. Reintroducing publishing would
require an explicit product and safety decision. Under the user's final scope
decision, there are no remaining v1.2 release blockers. v1.2 development ends here.
