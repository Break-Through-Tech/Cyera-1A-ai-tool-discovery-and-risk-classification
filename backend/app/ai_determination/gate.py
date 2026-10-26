"""The deterministic gate in front of the Jev judge (ADR 0002).

Patterns are copied unchanged from ``notebooks/ai_cascade/cascade_v2.py``, the configuration
measured on held-out pages; editing them is a new AI Determination version that needs re-validation.
"""

import re

KEYWORD = re.compile(
    r"\b(?:AI|AIOps|artificial[\s-]+intelligence|ML|machine[\s-]+learning|"
    r"deep[\s-]+learning|neural[\s-]+networks?|LLMs?|"
    r"large[\s-]+language[\s-]+models?|NLP|"
    r"natural[\s-]+language[\s-]+(?:processing|understanding)|"
    r"generative[\s-]+AI)\b", re.IGNORECASE)
CAPABILITY = re.compile(
    r"\b(?:GPT[\w.-]*|ChatGPT|OpenAI|Claude|Gemini|Llama|Midjourney|Stable[\s-]+Diffusion|DALL[\s·-]*E|transformers?|"
    r"(?:text|speech|voice|image|photo|screenshot|prompt|sketch|audio|video|pdf)s?[\s-]+to[\s-]+"
    r"(?:image|speech|text|video|code|music|voice|3D|SQL|flutter|html|react|website|app|formula)s?|"
    r"(?:plain|natural|everyday)[\s-]+(?:English|language)|chat[\s-]?bots?|copilots?|agentic|"
    r"virtual[\s-]+assistants?|voice[\s-]?(?:clon\w*|over\w*)|transcri(?:be|bes|bed|bing|ption|ptions)|"
    r"summari[sz](?:e|es|ed|ing|ation|ations|er)|paraphras\w*|upscal\w*|deepfakes?|face[\s-]?swap\w*|"
    r"computer[\s-]+vision|(?:speech|face|facial|image|object|handwriting)[\s-]+recognition|"
    r"predictive|learns\s+(?:from\s+)?(?:your|you)|ask\s+(?:it\s+)?(?:questions|anything)|"
    r"answers?\s+(?:your\s+|any\s+)?questions|generat(?:e|es|ed|ing|ion)\s+(?:\w+\s+){0,2}"
    r"(?:images?|art|artwork|videos?|music|songs?|voices?|text|copy|content|code|captions?|answers?|recipes?|"
    r"formulas?|logos?|avatars?|headshots?|stories|essays?|emails?|posts?|scripts?|lyrics|designs?|"
    r"presentations?|slides|quizzes|flashcards|summaries))\b", re.IGNORECASE)
MIN_TEXT_CHARS = 200
SNIPPET_CHARS = 300


def gate(text: str) -> bool:
    return bool(KEYWORD.search(text) or CAPABILITY.search(text))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+| \| ", text) if s.strip()]
