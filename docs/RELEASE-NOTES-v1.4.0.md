# v1.4.0 - SEO Parity and Multi-Agent Readiness

Release date: 2026-02-21

## Highlights

- Finalized major Claude-parity upgrades across audit and supporting skills.
- Added shipped specialist runner skills for audit tracks:
  - `skills/seo-performance`
  - `skills/seo-visual`
- Improved audit detail depth and report quality across technical, content, schema, sitemap, performance, and visual tracks.
- Added explicit Gemini chat setup guidance for experimental Multi-agent mode (`/experimental` -> enable **Multi-agent**).

## What Changed

- `seo-audit`
  - Upgraded orchestration and specialist synthesis behavior.
  - Added PageSpeed key forwarding to performance specialist orchestration.
  - Improved score derivation using richer visual/performance signals.
- `seo-technical`
  - Added mobile touch target diagnostics and scoring impact.
- `seo-content`
  - Added complex product-page threshold handling.
- `seo-schema`
  - Added Microdata and RDFa extraction/validation integration.
- `seo-sitemap`
  - Added location-page quality gates in analyze path.
- `seo-page`
  - Added explicit Recommendations section and summary export parity.
- `seo-images`
  - Aligned report structure with Image Audit Summary + Recommendations parity.
- `seo-plan`
  - Added Success Criteria section and competitor-input-aware analysis.
- `seo-programmatic`
  - Added explicit Index Bloat Prevention section in analysis report.
- Documentation
  - Updated README + architecture/commands docs to clarify multi-agent requirement and fallback behavior.

## Important Setup Note (Gemini Chat)

For authentic parallel `/seo audit` behavior in Gemini chat:

1. Run `/experimental`
2. Enable **Multi-agent**

If Multi-agent is OFF, chat execution may use a reduced/non-parallel delegation path.
Deterministic CLI runners remain available regardless of this toggle.

## Upgrade Notes

- No breaking CLI argument removals in this release.
- New specialist directories are included and should be copied during manual install:
  - `skills/seo-performance`
  - `skills/seo-visual`

## Full Diff

- Compare: `v1.3.1...v1.4.0`

