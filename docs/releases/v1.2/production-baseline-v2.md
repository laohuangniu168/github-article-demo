# Production Baseline v2

Status: ACTIVE for production baseline verification in this remediation candidate.
Sandbox execution remains blocked until the remediation is committed and manually
reviewed. This document does not authorize generation, publication, or Git writes.

## Authority and fixed membership

Schema version: `2`. Algorithm version: `git-content-sha256-manifest-v1`.
Canonical source: `GIT_REPOSITORY_CONTENT`.

The immutable release identity is
`2e3af01a520145648244eb235cf0f30651982818`. Read the following input files from
that commit, take the slug before `|`, and form `articles/<slug>.md`:

| Input | Count |
| --- | ---: |
| production-batch-001.txt | 10 |
| production-batch-002.txt | 20 |
| production-batch-003.txt | 50 |
| production-batch-004.txt | 100 |
| internal-link-production-batch-010.txt | 10 |
| direct-specified-link-production-010.txt | 10 |

Require exactly 200 unique paths. Do not enumerate the articles directory or use
current input files to expand membership. Existing sandbox articles, untracked
articles and Digest output are outside this set. Missing repository objects fail
closed; the verifier disables lazy fetching and never repairs the repository.

## Canonical format

For each selected path, read exact repository blob content bytes at a resolved
commit, equivalent to `git show <commit>:<relative_path>`. Compute SHA-256 over
those bytes, excluding the Git object header. Do not decode, normalize line
endings, strip BOMs, or read working-tree article bytes.

The manifest is an array of objects with exactly these fields:

```json
[{"relative_path":"articles/example.md","repository_content_sha256":"<64 lowercase hexadecimal digits>"}]
```

Sort records by relative path ascending using UTF-8 byte order. Paths use `/`,
are case-sensitive, and use the existing ASCII production slug grammar. Serialize
with `json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`,
encoded as UTF-8, without BOM, indentation, spaces or a trailing newline.

The aggregate is SHA-256 of these canonical manifest bytes. Consequently the
canonical manifest file SHA-256 and aggregate SHA-256 are identical. Commit IDs,
absolute roots, timestamps, Git blob OIDs and machine information do not enter
the aggregate payload. Release and inspected commit identities belong in the
companion report.

## Verification and evidence

`tools/production_baseline.py` rebuilds manifests without depending on saved
evidence. It verifies the current HEAD manifest against the pinned release
manifest, rejecting content drift and supplied manifests with missing, unknown,
duplicate or changed records. HEAD is resolved before content reads.

```text
python tools/production_baseline.py
```

The command is read-only and prints a report. To persist evidence, callers use
`build_production_baseline_manifest`, `canonical_manifest_bytes` and
`verify_production_baseline`, saving canonical bytes to
`output/digest/evidence/production-baseline-v2-manifest.json` and the verification
report to `output/digest/evidence/production-baseline-v2-report.json`.

Every future baseline Gate must preserve the 200-file manifest and report at
least entry count, manifest SHA-256, aggregate SHA-256, schema version, algorithm
version and inspected commit identity. Both evidence files remain Git ignored.
Evidence creation is separate from the read-only verifier. A lone aggregate is
not sufficient Gate evidence.

Worktree CRLF materialization, checkout location and input enumeration order do
not affect this algorithm. A separate worktree cleanliness check remains needed:
repository-only verification deliberately does not detect uncommitted edits.

## Legacy history

`LEGACY_PRODUCTION_AGGREGATE_SHA`:
`3fb3db1c70213e92ed1134f06b84f1408ffd0be66789247b79987fde0a621f4e`.

`LEGACY_ALGORITHM=UNKNOWN`, `LEGACY_SHA_REPRODUCIBLE=NO`,
`LEGACY_CONTENT_DRIFT_INDICATOR=NO`.

Investigation proved all 200 current production blobs equal the release blobs;
working-tree differences were solely CRLF materialization. The historical
aggregate construction was not recovered. Preserve the v1.1.1 release document
unchanged. V2 replaces the legacy SHA-only verification requirement, not the
historical fact, and never claims the new SHA reproduces the legacy value.
