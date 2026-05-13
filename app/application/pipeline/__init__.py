"""Application layer — use cases and pipeline."""

from app.application.pipeline.digital_pipeline import process_digital_invoice
from app.application.pipeline.extract_candidates import (
    Candidate,
    CandidateSet,
    extract_candidates,
)
from app.application.pipeline.normalize_document import (
    ExtractionSource,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
)

__all__ = [
    "process_digital_invoice",
    "Candidate",
    "CandidateSet",
    "extract_candidates",
    "ExtractionSource",
    "NormalizedBlock",
    "NormalizedDocument",
    "NormalizedPage",
]