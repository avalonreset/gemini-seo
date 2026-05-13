# Privacy

Gemini SEO runs locally in the user's agent session. The core skill does not
collect, transmit, or store personal data on behalf of this repository.

## Local Data

- SEO analysis outputs are written only where the user or workflow asks for them.
- API keys and OAuth tokens are read from environment variables or local config.
- Default project config path: `~/.config/gemini-seo/`.
- Default project cache path: `~/.cache/gemini-seo/`.

## External Services

Some optional workflows call third-party services when credentials are supplied:

- Google APIs
- DataForSEO
- Firecrawl
- Moz
- Bing Webmaster Tools
- Image generation providers

Those services are governed by their own privacy policies and terms. Do not
run credentialed workflows against private client sites unless you have the
right to process that data.

## Reports

Generated reports may include URLs, page text snippets, metadata, screenshots,
rankings, and API-derived SEO data. Review reports before sharing them outside
your organization.
