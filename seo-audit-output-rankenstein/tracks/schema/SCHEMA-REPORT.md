# Schema Report

## Source
- `https://rankenstein.pro/`

## Detection Summary
- JSON-LD scripts: 4
- Parsed JSON-LD blocks: 4
- Schema nodes with `@type`: 40
- Unique schema types: answer, contactpoint, entrypoint, faqpage, imageobject, offer, organization, person, quantitativevalue, question, searchaction, softwareapplication, thing, website
- Microdata markers: 0
- RDFa markers: 10

## Validation Summary
- Pass: 37
- Warn: 1
- Fail: 2
- Parse errors: 0

### Failures
- Block 2, node 3, `organization`: Missing required property for organization: name; Missing required property for organization: url
- Block 3, node 5, `organization`: Missing required property for organization: url

### Warnings
- Block 4, node 1, `faqpage`: FAQPage is restricted to government/health authority sites.

### Parse Errors
- None

## Opportunities
- **Article**: Article-like content signals detected without Article schema.
- **Product**: Product/pricing cues detected without Product schema.
