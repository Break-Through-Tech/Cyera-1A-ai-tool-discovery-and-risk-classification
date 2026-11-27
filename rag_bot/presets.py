"""Named retrieval settings shared by the terminal and Streamlit."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalPreset:
    key: str
    label: str
    strategy: str
    cutoff: float = 0.25
    limit: int = 5
    smoothing: int = 60
    depth: int = 20
    cap: int | None = 2

    def hybrid_config(self):
        from .hybrid import HybridConfig

        return HybridConfig(self.smoothing, self.depth, self.limit, self.cap)


SEMANTIC_STABLE = RetrievalPreset("semantic-stable", "Semantic — Stable", "semantic")
HYBRID_BASELINE = RetrievalPreset("hybrid-baseline", "Hybrid — Baseline", "hybrid")
HYBRID_CALIBRATED = RetrievalPreset(
    "hybrid-calibrated", "Hybrid — Calibrated (experimental)", "hybrid",
    smoothing=10, cap=None,
)
PRESETS = {preset.key: preset for preset in (SEMANTIC_STABLE, HYBRID_BASELINE, HYBRID_CALIBRATED)}
DEFAULT_PRESETS = {"semantic": SEMANTIC_STABLE, "hybrid": HYBRID_BASELINE}
