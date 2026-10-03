# On-demand tool metadata: HTTP extraction experiment

## Run it

From the project root:

```bash
python3 -m venv /tmp/cyera-enrichment-venv
/tmp/cyera-enrichment-venv/bin/pip install -r notebooks/metadata_enrichment/requirements.txt
/tmp/cyera-enrichment-venv/bin/python notebooks/metadata_enrichment/experiment.py --client requests
/tmp/cyera-enrichment-venv/bin/python notebooks/metadata_enrichment/experiment.py --client curl-cffi
```

No model is trained or run. This probes whether public HTML supplies usable functionality evidence. The client modes share extraction logic. Requests visits six fixed public sites; curl_cffi visits Claude and Asana. Dependencies are isolated from the application's empty root requirements file.

## What the code does

1. Fetch robots.txt and check the `ToolMetadataExperiment` agent. Explicit disallow prevents fetching the product page; 404/410 permits proceeding; other robots errors conservatively skip.
2. Fetch HTML with connection/read timeouts and a 2 MB decoded response limit.
3. Save raw HTML and robots responses.
4. Parse raw HTML bytes with Beautiful Soup, honoring HTML encoding declarations. Extract title, meta/Open Graph descriptions, and up to 20 H1/H2 headings.
5. Independently extract main text with Trafilatura.
6. Write URL, client, final URL, capture time, status, extraction results, and main-text preview to results.json.

curl_cffi uses `Session(impersonate='chrome')` to change the transport/browser fingerprint, while keeping an explicit experiment User-Agent. No JavaScript execution, CAPTCHA solving, authentication, or robots-disallow bypass is attempted. Redirects follow the client's default behavior. This is a fixed-site research script, NOT an arbitrary-URL production fetcher: destination/DNS/redirect SSRF protection and redirect-specific robots checks must precede application use.

Small inline assertions check metadata extraction, missing fields, and UTF-8 punctuation. Both client modes were executed successfully. Re-running overwrites that mode's captures; websites can change.

## Observed results

| Site | Requests | curl_cffi | Evidence and limitations |
|---|---|---|---|
| Hugging Face | 200 | Not tested | Explicit AI metadata; 1,024 characters of main text |
| Grammarly | 200 | Not tested | Explicit AI writing/text-generation metadata; 3,492 characters of main text |
| Slack | 200 | Not tested | AI-platform metadata; 4,221 characters of main text. Product capabilities do not prove observed AI-feature use |
| LibreOffice | 200 | Not tested | Meta description: `LibreOffice is a free office suite`. Trafilatura's 403-character result focuses on community contributions rather than product functionality |
| Claude | 403, final URL `/login` | **200**, final URL `/login`, 130,770 bytes | Useful meta description, despite login host. Trafilatura's 255-character result is business-registration/footer text, not product functionality |
| Asana app | Robots disallowed | Robots disallowed | Both clients received robots.txt with HTTP 200. Its wildcard rule is `Disallow: /`; neither client fetched the application page |

### Claude description recovered with curl_cffi

> Claude is Anthropic's AI, built for problem solvers. Tackle complex challenges, analyze data, write code, and think through your hardest work.

This is useful AI/functionality evidence. It is not a category prediction or proof of what an employee did. A single sequential comparison does not prove transport fingerprinting caused the changed response or establish reliable future access.

### Asana limitation

The robots file allows a list of named search crawlers but disallows other agents. The experiment does not impersonate those identities. We therefore know curl_cffi can retrieve its robots file, but we do NOT know whether it would retrieve a usable application page. A permitted, verified official product source or an unresolved result is needed instead.

## Implication for the classifier

Do not use only Trafilatura main text: Claude and LibreOffice show that successful fetching plus main-text extraction can still miss the best functionality evidence. Retain title, description, and relevant product text as separate source-qualified fields before constructing bounded model input. Do not include HTTP status, crawler identity, or error pages as classifier features. An absent AI keyword is not a reviewed non-AI label.

curl_cffi is worth evaluating as the fetch client; it could replace Requests rather than adding a permanent fallback stack. Beautiful Soup remains useful for explicit metadata. Trafilatura is optional supporting extraction, not the sole evidence source. No need for a full crawler/browser yet.

Next: review fetched evidence across a larger tool-level sample and measure metadata coverage separately from classifier accuracy. Test catalog-trained models against fetched functionality text to expose training/inference mismatch. Keep held-out tools out of training and known lookup.

## Files

- `experiment.py`: readable executable experiment.
- `requirements.txt`: exact installed versions from the isolated experiment environment.
- `captures/requests/results.json`: six-site baseline.
- `captures/curl-cffi/results.json`: Claude/Asana comparison.
- `captures/<client>/*.html`: raw returned HTML (including the Requests 403 response).
- `captures/<client>/*.robots.txt`: raw robots responses.
- `captures/<client>/*.text.txt`: extracted main text for successful HTML responses.

These are public-site research captures, not employee activity. Project architecture decisions and application dependencies were not changed.
