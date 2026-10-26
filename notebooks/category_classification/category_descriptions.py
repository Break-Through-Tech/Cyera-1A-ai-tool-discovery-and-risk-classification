"""One description per AIToolBuzz Category, written from the category names and train-split examples only.

Zero-shot embeddings and the Jev question both read these. Editing them changes those methods' frozen configuration.
"""

CATEGORY_DESCRIPTIONS = {
    "Ai And Machine Learning": "General-purpose AI tools and model tooling: AI assistants and chatbots, text "
                               "summarizers and rewriters, prompt tools, and platforms for building, training, or "
                               "serving machine-learning models.",
    "Business And Finance": "Tools for running a business or managing money: accounting, invoicing, payments, "
                            "investing and trading, financial analysis, startup and pitch help, competitive "
                            "intelligence, and business planning.",
    "Communication And Support": "Tools for conversations and assistance: customer-service chatbots, help desks, "
                                 "email and messaging assistants, outreach, virtual assistants, and question "
                                 "answering for users.",
    "Creative And Entertainment": "Tools for fun, art, and entertainment: art and character generators, memes, "
                                  "games, stories, avatars, costume and novelty image ideas, and coloring pages.",
    "Data And Analytics": "Tools for working with data: querying databases, text to SQL, spreadsheet and document "
                          "analysis, dashboards, charts, research and insights from data or feedback.",
    "Education And Learning": "Tools for teaching and studying: tutoring, homework and math solvers, courses, "
                              "quizzes, language learning, exam preparation, and resources for students and "
                              "teachers.",
    "Industry Specific": "Tools built for one profession or sector: legal, healthcare and clinical notes, real "
                         "estate listings, construction and heavy equipment, agriculture, and other vertical "
                         "industries.",
    "Marketing And Sales": "Tools for promotion and selling: SEO and keyword research, ad creatives and campaigns, "
                           "social media and LinkedIn growth, lead generation, sales outreach, and brand "
                           "visibility.",
    "Media And Content Creation": "Tools that produce or edit media and written content: image and video "
                                  "generation and editing, text to speech, voice, music, writing and blogging, "
                                  "and photo enhancement.",
    "Operations And Management": "Tools for getting work done in an organization: productivity, meeting notes, "
                                 "project and task management, workflow automation, scheduling, HR and employee "
                                 "support.",
    "Personal And Lifestyle": "Tools for an individual's personal life: health, fitness, and mental wellbeing, "
                              "relationships and companionship, travel, fashion and beauty, gifts, careers, and "
                              "tarot or astrology.",
    "Security And Privacy": "Tools for protecting content, data, and identity: AI-content detection and "
                            "authenticity checks, plagiarism checks, content moderation, identity verification, "
                            "data loss prevention, and cybersecurity.",
    "Specialized Technologies": "Tools built on a specific technology rather than a business function: robotics, "
                                "speech recognition and transcription engines, computer vision, QR codes, APIs "
                                "and hardware, and other niche technical products.",
    "Technology And Development": "Tools for software builders: coding assistants, developer tools and SDKs, "
                                  "no-code and app builders, APIs, testing, DevOps, and monitoring of software or "
                                  "language-model usage.",
}
