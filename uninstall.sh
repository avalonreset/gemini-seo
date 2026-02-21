#!/usr/bin/env bash
set -euo pipefail

main() {
    CODEX_ROOT="${CODEX_HOME:-${HOME}/.codex}"
    echo "→ Uninstalling Codex SEO..."

    # Remove main skill (includes venv and requirements.txt)
    rm -rf "${CODEX_ROOT}/skills/seo"

    # Remove sub-skills
    for skill in seo-audit seo-competitor-pages seo-content seo-geo seo-hreflang seo-images seo-page seo-plan seo-programmatic seo-schema seo-sitemap seo-technical; do
        rm -rf "${CODEX_ROOT}/skills/${skill}"
    done

    # Remove agent profiles
    for agent in \
        seo-competitor-pages \
        seo-content \
        seo-geo \
        seo-hreflang \
        seo-images \
        seo-performance \
        seo-plan \
        seo-programmatic \
        seo-schema \
        seo-sitemap \
        seo-technical \
        seo-visual; do
        rm -f "${CODEX_ROOT}/agents/${agent}.md"
    done

    echo "✓ Codex SEO uninstalled."
}

main "$@"
