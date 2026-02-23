#!/usr/bin/env bash
set -euo pipefail

# Gemini SEO Installer
# Wraps everything in main() to prevent partial execution on network failure

main() {
    Gemini_ROOT="${Gemini_HOME:-${HOME}/.Gemini}"
    SKILL_DIR="${Gemini_ROOT}/skills/seo"
    AGENT_DIR="${Gemini_ROOT}/agents"
    REPO_URL="https://github.com/avalonreset/gemini-seo"
    RAW_URL="https://raw.githubusercontent.com/avalonreset/gemini-seo/main"

    echo "========================================"
    echo "  Gemini SEO - Installer"
    echo "  Gemini Skill Suite"
    echo "========================================"
    echo ""

    # Check prerequisites
    command -v python3 >/dev/null 2>&1 || { echo "[ERROR] Python 3 is required but not installed."; exit 1; }
    command -v git >/dev/null 2>&1 || { echo "[ERROR] Git is required but not installed."; exit 1; }

    # Check Python version
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo "[OK] Python ${PYTHON_VERSION} detected"

    # Create directories
    mkdir -p "${SKILL_DIR}"
    mkdir -p "${AGENT_DIR}"

    # Clone or update
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf ${TEMP_DIR}" EXIT

    echo "[INFO] Downloading Gemini SEO..."
    git clone --depth 1 "${REPO_URL}" "${TEMP_DIR}/gemini-seo" 2>/dev/null

    # Copy skill files
    echo "[INFO] Installing skill files..."
    cp -r "${TEMP_DIR}/gemini-seo/seo/"* "${SKILL_DIR}/"

    # Copy sub-skills
    if [ -d "${TEMP_DIR}/gemini-seo/skills" ]; then
        for skill_dir in "${TEMP_DIR}/gemini-seo/skills"/*/; do
            skill_name=$(basename "${skill_dir}")
            target="${Gemini_ROOT}/skills/${skill_name}"
            mkdir -p "${target}"
            cp -r "${skill_dir}"* "${target}/"
        done
    fi

    # Copy schema templates
    if [ -d "${TEMP_DIR}/gemini-seo/schema" ]; then
        mkdir -p "${SKILL_DIR}/schema"
        cp -r "${TEMP_DIR}/gemini-seo/schema/"* "${SKILL_DIR}/schema/"
    fi

    # Copy reference docs
    if [ -d "${TEMP_DIR}/gemini-seo/pdf" ]; then
        mkdir -p "${SKILL_DIR}/pdf"
        cp -r "${TEMP_DIR}/gemini-seo/pdf/"* "${SKILL_DIR}/pdf/"
    fi

    # Copy agent profiles
    echo "[INFO] Installing agent profiles..."
    cp -r "${TEMP_DIR}/gemini-seo/agents/"*.md "${AGENT_DIR}/" 2>/dev/null || true

    # Copy shared scripts
    if [ -d "${TEMP_DIR}/gemini-seo/scripts" ]; then
        mkdir -p "${SKILL_DIR}/scripts"
        cp -r "${TEMP_DIR}/gemini-seo/scripts/"* "${SKILL_DIR}/scripts/"
    fi

    # Copy hooks
    if [ -d "${TEMP_DIR}/gemini-seo/hooks" ]; then
        mkdir -p "${SKILL_DIR}/hooks"
        cp -r "${TEMP_DIR}/gemini-seo/hooks/"* "${SKILL_DIR}/hooks/"
        chmod +x "${SKILL_DIR}/hooks/"*.sh 2>/dev/null || true
        chmod +x "${SKILL_DIR}/hooks/"*.py 2>/dev/null || true
    fi

    # Copy requirements.txt to skill dir so users can retry later
    cp "${TEMP_DIR}/gemini-seo/requirements.txt" "${SKILL_DIR}/requirements.txt" 2>/dev/null || true

    # Install Python dependencies (venv preferred, --user fallback)
    echo "[INFO] Installing Python dependencies..."
    VENV_DIR="${SKILL_DIR}/.venv"
    if python3 -m venv "${VENV_DIR}" 2>/dev/null; then
        "${VENV_DIR}/bin/pip" install --quiet -r "${TEMP_DIR}/gemini-seo/requirements.txt" 2>/dev/null && \
            echo "  [OK] Installed in venv at ${VENV_DIR}" || \
            echo "  [WARN] Venv pip install failed. Run: ${VENV_DIR}/bin/pip install -r ${SKILL_DIR}/requirements.txt"
    else
        pip install --quiet --user -r "${TEMP_DIR}/gemini-seo/requirements.txt" 2>/dev/null || \
        echo "  [WARN] Could not auto-install. Run: pip install --user -r ${SKILL_DIR}/requirements.txt"
    fi

    # Optional: Install Playwright browsers (for screenshot analysis)
    echo "[INFO] Installing Playwright browsers (optional, for visual analysis)..."
    if [ -f "${VENV_DIR}/bin/playwright" ]; then
        "${VENV_DIR}/bin/python" -m playwright install chromium 2>/dev/null || \
        echo "  [WARN] Playwright install failed. Visual analysis will use WebFetch fallback."
    else
        python3 -m playwright install chromium 2>/dev/null || \
        echo "  [WARN] Playwright install failed. Visual analysis will use WebFetch fallback."
    fi

    echo ""
    echo "[OK] Gemini SEO installed successfully!"
    echo ""
    echo "Usage:"
    echo "  1. Start Gemini"
    echo "  2. Ask for SEO workflows (e.g., full audit, technical audit, schema validation)"
    echo ""
    echo "Python deps location: ${SKILL_DIR}/requirements.txt"
    echo "To uninstall: curl -fsSL ${RAW_URL}/uninstall.sh | bash"
}

main "$@"

