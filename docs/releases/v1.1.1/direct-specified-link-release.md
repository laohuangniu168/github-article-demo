# v1.1.1 DIRECT Specified Link Release

## Release identity

- Version: v1.1.1
- Status: RELEASED
- Release commit: `2e3af01a520145648244eb235cf0f30651982818`
- GitHub Pages run: `32861525777`
- Pages deployed SHA: `2e3af01a520145648244eb235cf0f30651982818`
- Production articles: 200
- Production 200 aggregate SHA-256: `3fb3db1c70213e92ed1134f06b84f1408ffd0be66789247b79987fde0a621f4e`

## DIRECT contract

- Mode status: `PRODUCTION_VALIDATED`
- Input format: `id|url|anchor`
- Approval source: `USER_INPUT`
- Allowed schemes: `http`, `https`
- Configured links per article: explicit integer from 1 through 30; there is no production default
- Target preflight, redirect, HTTP status, semantic validation, and cluster matching are non-blocking in DIRECT mode
- Protected-zone enforcement, exact provenance, and final Internal Link regression remain mandatory
- Placement types: `NATURAL_ANCHOR` and `VISIBLE_REFERENCE`
- Visible reference format: `| 详见 [anchor](user_approved_url)`

DIRECT preserves the exact approved URL. It does not upgrade protocols, follow redirects, or substitute a final destination.

## STRICT mode remains independent

STRICT Specified Link remains healthy and was not replaced or relaxed by DIRECT. Its preflight, cluster, quantity, Registry, Planner, Injector, and Audit contracts remain unchanged. DIRECT and STRICT are separate production paths.

## Internal Link remains frozen

The v1.1 Internal Link contract remains unchanged:

- Default configured maximum: 30
- Allowed range: 20–50
- Minimum relevance score: 40
- Same-batch cap: 35%
- Body target: 70%
- Related maximum: 10
- Inbound cap: `max(2, ceil(batch_size × 0.20))`

DIRECT did not change the Internal Link contract.

## Production validation

- Trial articles: 10
- Internal links: 144
- DIRECT links: 20
- Combined links: 164
- Unique DIRECT URLs: 20
- DIRECT URL usage min/max: 1/1
- Post-injection Quality: 10/10 PASS
- Similarity maximum: 17.39%; at least 45%: 0; at least 60%: 0
- Jekyll Safety: 10/10 PASS
- Public articles: 10/10 HTTP 200
- Public DIRECT hrefs: 20/20
- Public Internal Link smoke: PASS

## Frozen implementation SHA-256

### DIRECT

- Registry: `d5aaa4b9619ec5953f8f331d003123ecd45cac9fd038ca6293a2ff7d601f3754`
- Planner: `c724e46cae78b9375ab84a8f80b1ea9cdf4a8321d142d6bf5fa5cb16b793ac0e`
- Injector: `7cc3e1b3dc61bf418456cf3bbff59da2f8e9a0068196aa38851f7dfb0d213b39`
- Audit: `0c51e718c237fb0d4334c34f933c64dc7ca0ae6f392395fc4d02d3abd59059ca`

### STRICT

- Registry: `d98e18df74c91e2a63f555453456749f12163029e69de5562818872ebe6d8ae2`
- Planner: `f809fcee3412a2fcac90beeeac061b3aec84787da4f9978360db4370fff74a8d`
- Injector: `bae676b79ea0260a60d48bb6f55cc55f994a01553016994e1d70ac853111bf58`
- Audit: `e826cae3e3a6bcfb23f729ef08f5072ac6eeec82a99b342e9eec5431af3903a7`

### Internal and Generation Adapter

- Internal Registry: `4980106ab148672ae1df91da2b6dc54fc2763a877a59286ed9f390a7d10e2a8d`
- Internal Selector: `fbea4226209b25976fb26f3d7cc29f7b1fb6ec176daf6a3bfb674d96dbaf505e`
- Internal Injector: `b6c1efbbbe1e555f6e9caafaa69c3394129ba415df209c975bbb071182ca9660`
- Internal Audit: `ff88631f5a6520ada1f7c7171bc6515d1be5727753b40f7242ebd23813b5bc3c`
- Generation Adapter: `5124ee7802dee8563971ca42d99ff3ec8f9ca859fe82a36432a091dd208e7d7e`

## Known limitations

These are intentional v1.1.1 boundaries, not release blockers:

- Anchors must be supplied explicitly by the user.
- DIRECT does not retrieve titles or validate target-site content quality.
- Target HTTP status does not block DIRECT.
- There is no automatic anchor variation or cross-cluster model.
- Existing articles are not backfilled.
- SEO Agent is not integrated.
- The configured link count must be explicit.
- Ambiguous safety structure continues to fail closed.
- The user-approved meaning owns responsibility for final target reachability.

## Deferred to v1.2

- SEO Agent integration
- Existing-article backfill
- Automatic anchor generation and variants
- Complex distribution strategies
- Optional title retrieval and metadata enrichment
- Target monitoring and batch-site management
- Additional placement strategies
- `nofollow` / `sponsored` and priority controls
- 300 links per article

This closure document is intentionally untracked. Publishing it requires a separate Release Documentation Commit Gate.
