# Installation Guide

Gemini SEO is packaged natively for the Gemini CLI using the `.skill` format. You do not need to manually copy folders or run complex shell scripts.

## Option 1: Install from Release (Recommended)

1. Go to the GitHub Releases page and download the latest `gemini-seo.skill` file.
2. Open your terminal and run the Gemini CLI installation command:
   ```bash
   gemini skills install path/to/gemini-seo.skill --scope user
   ```
3. Open the Gemini CLI (or restart it if it's already open).
4. Run the reload command to ensure the skill is loaded into your context:
   ```
   /skills reload
   ```
5. Verify the installation:
   ```
   /skills list
   ```
   You should see `gemini-seo` listed.

## Option 2: Build from Source

If you want to modify the skill or build it from the raw source code:

1. Clone the repository:
   ```bash
   git clone https://github.com/avalonreset/gemini-seo.git
   cd gemini-seo
   ```
2. Ensure you have the `skill-creator` tool available, and run the packager:
   ```bash
   node path/to/skill-creator/scripts/package_skill.cjs .
   ```
3. The script will validate the project and output a `gemini-seo.skill` file.
4. Install it using the command from Option 1.

## Python Dependencies

Gemini SEO uses a few small Python scripts (like `fetch_page.py`) to safely interact with the live web and bypass basic bot protections. 

Ensure you have Python 3 installed on your system. If a script fails during an audit, you may need to install the dependencies manually:
```bash
pip install playwright beautifulsoup4
python -m playwright install chromium
```