# Training label review

The experimental overrides cover the two specific corrections discussed with the
user. The earlier local review queue was absent, so the exact IDs and evidence were
checked against the frozen training CSV. The frozen source and validation labels
are preserved.

| Training example | Original category | Experimental category | Evidence |
|---|---|---|---|
| Prospectli (`0cf959db…`) | Business And Finance | Marketing And Sales | The description identifies B2B prospect identification, qualification and engagement as the tool's function. |
| General-purpose photorealistic image generator (`9b6e9613…`) | Creative And Entertainment | Media And Content Creation | The description says it generates photorealistic images with AI and gives no specialized purpose. Its previously reviewed counterpart (`51d02207…`) describes the same general function and already carries the media label. |

General-purpose image generation and editing use Media And Content Creation.
Specific uses such as recreational coloring pages and ad creative production
need a primary-function review before any override. Photo-to-art tools and
other ambiguous pairs remain in the review scope for a future batch.
