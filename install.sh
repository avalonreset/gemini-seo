#!/usr/bin/env bash
set -euo pipefail

main() {
    REPO_URL="${GEMINI_SEO_REPO_URL:-https://github.com/avalonreset/gemini-seo}"
    REPO_TAG="${GEMINI_SEO_TAG:-v1.9.9}"
    TARGETS="${GEMINI_SEO_TARGETS:-gemini}"

    echo "========================================"
    echo "  Gemini SEO - Installer"
    echo "========================================"
    echo ""

    command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required but not installed."; exit 1; }
    command -v git >/dev/null 2>&1 || { echo "Git is required but not installed."; exit 1; }

    PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    PYTHON_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')"
    if [ "${PYTHON_OK}" = "0" ]; then
        echo "Python 3.10+ is required but ${PYTHON_VERSION} was found."
        exit 1
    fi
    echo "Python ${PYTHON_VERSION} detected"

    TEMP_DIR="$(mktemp -d)"
    trap 'rm -rf "${TEMP_DIR}"' EXIT
    REPO_DIR="${TEMP_DIR}/gemini-seo"

    echo "Downloading Gemini SEO (${REPO_TAG})..."
    git clone --depth 1 --branch "${REPO_TAG}" "${REPO_URL}" "${REPO_DIR}" >/dev/null 2>&1

    IFS=',' read -ra TARGET_LIST <<< "${TARGETS}"
    for target in "${TARGET_LIST[@]}"; do
        target="$(printf '%s' "${target}" | tr '[:upper:]' '[:lower:]' | xargs)"
        case "${target}" in
            gemini)
                install_target "${REPO_DIR}" "${HOME}/.gemini/skills" "${HOME}/.gemini/agents" "gemini"
                ;;
            codex)
                CODEX_BASE="${CODEX_HOME:-${HOME}/.codex}"
                install_target "${REPO_DIR}" "${CODEX_BASE}/skills" "${CODEX_BASE}/agents" "codex"
                ;;
            claude)
                install_target "${REPO_DIR}" "${HOME}/.claude/skills" "${HOME}/.claude/agents" "claude"
                ;;
            "")
                ;;
            *)
                echo "Unknown install target '${target}'. Check GEMINI_SEO_TARGETS."
                exit 1
                ;;
        esac
    done

    echo ""
    echo "Gemini SEO installed successfully."
    echo "Run an SEO workflow with: /seo audit https://example.com"
}

install_target() {
    repo_dir="$1"
    skill_root="$2"
    agent_root="$3"
    label="$4"

    echo "Installing ${label} skill files into ${skill_root}..."
    mkdir -p "${skill_root}" "${agent_root}"

    # Full bundle for package formats that expect one top-level skill directory.
    bundle_dir="${skill_root}/gemini-seo"
    rm -rf "${bundle_dir}"
    mkdir -p "${bundle_dir}"
    cp -R "${repo_dir}/SKILL.md" "${bundle_dir}/"
    for dir in skills agents scripts schema docs extensions hooks pdf tests; do
        if [ -d "${repo_dir}/${dir}" ]; then
            cp -R "${repo_dir}/${dir}" "${bundle_dir}/${dir}"
        fi
    done
    cp "${repo_dir}/requirements.txt" "${bundle_dir}/requirements.txt" 2>/dev/null || true

    # Individual skills for skill loaders that auto-discover one directory per skill.
    for skill_dir in "${repo_dir}/skills"/*; do
        [ -d "${skill_dir}" ] || continue
        skill_name="$(basename "${skill_dir}")"
        target_dir="${skill_root}/${skill_name}"
        mkdir -p "${target_dir}"
        cp -R "${skill_dir}/." "${target_dir}/"
    done

    seo_dir="${skill_root}/seo"
    for dir in scripts schema hooks pdf extensions; do
        if [ -d "${repo_dir}/${dir}" ]; then
            mkdir -p "${seo_dir}/${dir}"
            cp -R "${repo_dir}/${dir}/." "${seo_dir}/${dir}/"
        fi
    done
    cp "${repo_dir}/requirements.txt" "${seo_dir}/requirements.txt" 2>/dev/null || true

    if [ -d "${repo_dir}/agents" ]; then
        cp -R "${repo_dir}/agents/"*.md "${agent_root}/" 2>/dev/null || true
    fi

    if [ "${GEMINI_SEO_INSTALL_DEPS:-1}" = "1" ] && [ -f "${repo_dir}/requirements.txt" ]; then
        venv_dir="${seo_dir}/.venv"
        if python3 -m venv "${venv_dir}" 2>/dev/null; then
            "${venv_dir}/bin/pip" install --quiet -r "${repo_dir}/requirements.txt" 2>/dev/null || \
                echo "Dependency install failed for ${label}. Retry: ${venv_dir}/bin/pip install -r ${seo_dir}/requirements.txt"
        else
            python3 -m pip install --quiet --user -r "${repo_dir}/requirements.txt" 2>/dev/null || \
                echo "Dependency install failed for ${label}. Retry: python3 -m pip install --user -r ${seo_dir}/requirements.txt"
        fi
    fi
}

main "$@"
