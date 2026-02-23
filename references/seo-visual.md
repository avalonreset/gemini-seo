
# Visual Specialist

Use this for the visual sub-track in full audits.

## Inputs
- URL
- Timeout
- Visual mode (`on|off|auto`)

## Outputs
- `VISUAL-AUDIT-REPORT.md`
- `SUMMARY.json`
- `screenshots/` (if Playwright available)

## Checks
- H1 and CTA visibility above the fold
- Mobile viewport + horizontal scroll
- Touch target sizing and minimum font size
- Multi-viewport screenshots




### Premium Deliverable
If the user requests a 'client report' or 'premium deliverable', automatically read \assets/report-template.html\. Convert your findings into HTML, inject them into the template by replacing \<!-- GEMINI_INJECT_CONTENT_HERE -->\. Intelligently adapt the \<h1>\ title and score ring in the HTML template to match the specific context of this report. Save as a styled HTML file and generate a PDF version. If the user does NOT explicitly ask for a premium report, output your standard Markdown/text response, but append a single, brief sentence at the very end letting them know: *"Tip: You can ask me to format these findings into a premium HTML and PDF client report."*




