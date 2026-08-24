# Internal Link Network v1.1 Release Closure

- Release version: v1.1
- Release date: 2026-08-24
- Gate 10 pre-closure HEAD: `20ef5eeb258c9dc15b30cbff37626c2f785f1738`
- Release closure commit: the commit containing this document and the Generation Adapter; its SHA is recorded in the Gate 10 final report.
- Frozen Registry: `ilr1:a9cffcfb40d71d5d029be0ebcb7b3495ffcd2a968716683e04faf2a0d1cb505f`
- Gate 9 Resume #2 report SHA-256: `290845e1cd3e3cfbbadbf1702c172e9fb1bf724d4d037cb430a034431894d7a7`
- Release status at closure: READY FOR PRODUCTION, pending independent push authorization.

## Production implementation inventory

| File | Role | Pre-closure provenance | SHA-256 |
|---|---|---|---|
| `tools/article_spec.py` | Parse and validate canonical two/three-field article specifications and cluster provenance | `3e1f7e4c8f15062842374ba6048d01764948c12d` | `372b3bb3ef98b366a48b43ed0aa2d90b33771c1635f2498aca5f0b473e5d9a79` |
| `tools/internal_link_registry.py` | Build the immutable Existing Production target registry | `3e1f7e4c8f15062842374ba6048d01764948c12d` | `4980106ab148672ae1df91da2b6dc54fc2763a877a59286ed9f390a7d10e2a8d` |
| `tools/internal_link_selector.py` | Resolve relevant candidates and enforce selection/inbound constraints | `6cf098ad530adecf351d60b829cb4ebb34e38033` | `fbea4226209b25976fb26f3d7cc29f7b1fb6ec176daf6a3bfb674d96dbaf505e` |
| `tools/internal_link_injector.py` | Perform protected-zone-safe Body/Related placement and final same-batch enforcement | `20ef5eeb258c9dc15b30cbff37626c2f785f1738` | `b6c1efbbbe1e555f6e9caafaa69c3394129ba415df209c975bbb071182ca9660` |
| `tools/internal_link_audit.py` | Independently audit final Markdown, provenance and batch constraints | `20ef5eeb258c9dc15b30cbff37626c2f785f1738` | `ff88631f5a6520ada1f7c7171bc6515d1be5727753b40f7242ebd23813b5bc3c` |
| `tools/internal_link_generation_adapter.py` | Deterministically project canonical `slug|title|cluster` input to generator-safe `slug|title` bytes and SHA-bound mapping evidence | Gate 9R2; tracked by the release closure commit | `5124ee7802dee8563971ca42d99ff3ec8f9ca859fe82a36432a091dd208e7d7e` |

Associated release tests are `tools/test_internal_link_registry.py`, `tools/test_internal_link_selector.py`, `tools/test_internal_link_injector.py`, `tools/test_internal_link_audit.py`, and `tools/test_internal_link_generation_adapter.py`.

The release inventory contains no temporary debug branch, hard-coded Gate 7/8/9 slug, hard-coded evidence result, random production URL, API secret, or local absolute production dependency. The Adapter default evidence directory is project-relative, configurable through `--evidence-dir`, and stores SHA-bound operational provenance.

## Frozen production contract

- Default internal links/configured maximum: 30.
- Allowed configured range: 20–50.
- Minimum relevance score: 40.
- Same-batch maximum: 35% of the final actual placement set.
- Inbound cap: `max(2, ceil(batch_size * 0.20))`.
- Body target ratio: 0.70.
- Related block maximum: 10.
- Body placement: at most one link per natural paragraph and three per H2 section.
- Relative target URL: `./{slug}.html`.
- Canonical target URL: `https://laohuangniu168.github.io/github-article-demo/articles/{slug}.html`.
- Selection shortfall reasons: `INSUFFICIENT_RELEVANT_CANDIDATES` and `INBOUND_CAP_EXHAUSTED`.
- Safe placement shortfall reason: `INSUFFICIENT_SAFE_INJECTION_POINTS`.
- Post-placement evidence: `SAME_BATCH_LIMIT_REACHED`.

The minimum of 20 is not permission to add irrelevant links. Safety, relevance, inbound, anchor, protected-zone and final same-batch constraints take priority. A verified result below 20 is a valid `PASS_WITH_SHORTFALL`; low-relevance links must never be used to fill the count.

## Production input contract

Canonical input accepts `slug|title` or `slug|title|cluster`; production should prefer the three-field form. When cluster is present, the Generation Adapter must create deterministic two-field `slug|title` input for the existing AI generator and retain `CLUSTER_PROVENANCE=CANONICAL_INPUT` in SHA-bound mapping evidence.

Passing three fields directly to the old generation CLI is prohibited because its two-field parser leaks the cluster suffix into the title, Front Matter and H1.

`GENERATION_ADAPTER_REQUIRED_FOR_PRODUCTION=YES`.

## Frozen production pipeline

1. Canonical Input
2. Generation Adapter
3. AI Content Generation
4. Pre-Injection Quality Audit
5. Frozen Registry Snapshot
6. Batch Registry Extension
7. Candidate Selection
8. Safe Link Injection
9. Internal Link Audit
10. Post-Injection Quality
11. Similarity Audit
12. Jekyll Safety
13. Git Controlled Publish
14. GitHub Pages Deploy
15. Public URL Verification

Every stage is fail-closed. Quality, Audit, Jekyll or public verification failure stops all later stages. A failed public verification is never a successful release.

## Gate evidence inventory

| Gate/path | Classification | Purpose |
|---|---|---|
| Gate 7 original unverifiable trial state | ABANDONED | Historical state lacked trustworthy complete provenance; it must not be used as release evidence. |
| Gate 7R provenance recovery | SUPERSEDED | Remediation path that enabled the final reproducible run. |
| `internal-link-sandbox-010-baseline.json` | VALID | Gate 7 final baseline. |
| `internal-link-sandbox-010-injection-results.json` | VALID | Gate 7 final injection provenance. |
| `internal-link-sandbox-010-gate7-report.json` | VALID | Gate 7 final PASS. |
| `internal-link-production-trial-020-gate8-report.json` | FAILURE_EVIDENCE | Gate 8 initial malformed-link false-positive failure; retained unchanged. |
| Gate 6R2 remediation history | SUPERSEDED | Compatibility remediation leading to the final audit baseline. |
| `internal-link-production-trial-020-baseline.json` | VALID | Gate 8 trusted baseline. |
| `internal-link-production-trial-020-injection-results.json` | VALID | Gate 8 injection provenance. |
| `internal-link-production-trial-020-gate8-resume-report.json` | VALID | Gate 8 final PASS. |
| `internal-link-production-validation-050-gate9-report.json` | FAILURE_EVIDENCE | Initial LOCAL TEMPLATE generation failure. |
| Gate 9R diagnosis | SUPERSEDED | Identified invocation and two/three-field interface errors. |
| Gate 9R2 Adapter validation and mapping files | VALID | Proven deterministic canonical-to-generation projection. |
| `internal-link-production-validation-050-gate9-restart-report.json` | FAILURE_EVIDENCE | Post-injection same-batch cap failure. |
| Gate 5R2 remediation history | SUPERSEDED | Added deterministic final-placement same-batch enforcement. |
| `internal-link-production-validation-050-baseline.json` | VALID | Trusted Gate 9 pre-injection content. |
| `internal-link-production-validation-050-injection-results.json` | FAILURE_EVIDENCE | Original pre-Gate5R2 placement evidence; retained unchanged. |
| `internal-link-production-validation-050-gate9-resume2-injection-results.json` | VALID | Final Gate5R2 placement provenance. |
| `internal-link-production-validation-050-gate9-resume2-report.json` | VALID | Gate 9 final PASS. |

Historical failure and superseded evidence must not be deleted or rewritten.

## Gate 9 production evidence

- Batch: `internal-link-production-validation-050`.
- Audit: PASS 6, PASS_WITH_SHORTFALL 44, FAIL 0.
- Links: 774 total, 300 Body, 474 Related, 200 same-batch, 574 Frozen.
- Per article: average 15.48, minimum 10, maximum 24.
- Maximum same-batch ratio: 33.33%.
- Inbound maximum/cap: 7/10.
- All safety and relevance violations: 0.
- Post-injection quality: 50/50 PASS.
- Similarity: maximum 22.26%, no pair at or above 45% or 60%.
- Jekyll safety: 50/50 PASS.
- Network distribution: PASS.

The observed 15.48 average is the safe production result and is not a defect to be filled by weakening frozen constraints.

## Rollback and fail-closed contract

- Generation failure: delete only unpublished files from the new batch; Existing Production remains untouched.
- Quality failure: do not build the Batch Registry Extension and do not inject.
- Selector failure: do not inject.
- Injector failure: restore the new batch from trusted `pre_injection_markdown`.
- Audit failure: restore the trusted baseline; never infer a baseline from final Markdown.
- Failure before commit: do not commit.
- Failure after commit but before push: retain commit evidence and wait for independent authorization; do not rewrite history automatically.
- Pages failure after push: do not alter Existing Production to hide it; enter a separate Deployment Recovery gate.
- Public URL verification failure: do not announce deployment success.

The trusted provenance tuple is `pre_injection_markdown`, `InjectionResult`, `registry_version`, `extension_version`, `config_version`, and `batch_id`.

## Known limitations and operating boundary

1. v1.1 does not backfill the Existing Production 180 articles.
2. v1.1 does not support 300 links per article.
3. The safe actual link count may be below 20.
4. `PASS_WITH_SHORTFALL` is a valid production outcome with verified provenance.
5. Only controlled clusters are supported.
6. Production publishing requires separate Git push authorization.
7. SEO Agent integration is outside Gate 10 and v1.1.
8. Trial articles, temporary inputs and raw `sandbox_evidence/` remain outside the release commit.

No GitHub Pages deployment, Existing Production rewrite, SEO Agent integration, v1.2 work or backfill is authorized by this closure.
