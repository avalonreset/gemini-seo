#!/usr/bin/env bash
set -euo pipefail

TARGETS="${GEMINI_SEO_TARGETS:-gemini,codex,claude}"

remove_target() {
    skill_root="$1"
    agent_root="$2"
    label="$3"

    removed_skills=0
    removed_agents=0

    for path in "${skill_root}/gemini-seo" "${skill_root}/seo" "${skill_root}"/seo-*; do
        if [ -e "${path}" ]; then
            rm -rf "${path}"
            removed_skills=$((removed_skills + 1))
        fi
    done

    for path in "${agent_root}"/seo-*.md; do
        if [ -e "${path}" ]; then
            rm -f "${path}"
            removed_agents=$((removed_agents + 1))
        fi
    done

    echo "${label}: removed ${removed_skills} skill dirs and ${removed_agents} agent files."
}

IFS=',' read -ra TARGET_LIST <<< "${TARGETS}"
for target in "${TARGET_LIST[@]}"; do
    target="$(printf '%s' "${target}" | tr '[:upper:]' '[:lower:]' | xargs)"
    case "${target}" in
        gemini)
            remove_target "${HOME}/.gemini/skills" "${HOME}/.gemini/agents" "gemini"
            ;;
        codex)
            CODEX_BASE="${CODEX_HOME:-${HOME}/.codex}"
            remove_target "${CODEX_BASE}/skills" "${CODEX_BASE}/agents" "codex"
            ;;
        claude)
            remove_target "${HOME}/.claude/skills" "${HOME}/.claude/agents" "claude"
            ;;
        "")
            ;;
        *)
            echo "Unknown target '${target}'."
            exit 1
            ;;
    esac
done
