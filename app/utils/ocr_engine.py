"""OCR engine adapter layer.

Wraps PaddleOCR behind a small interface so the rest of the app never
imports paddleocr directly. Import of the paddleocr/paddlepaddle packages
is deferred to PaddleOCREngine.__init__, so simply importing this module
never requires the dependency to be installed, and a missing/broken
dependency is surfaced as a clear OCRDependencyError instead of crashing
the app.

This module only extracts raw text, per-block confidence, and bounding
boxes - it does not perform answer extraction, template region matching,
or marking.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Protocol


class OCRDependencyError(Exception):
    """Raised when the configured OCR engine's dependency is unavailable
    or fails to initialize."""


@dataclass
class TextBlockResult:
    text: str
    confidence: Optional[float]
    box: List[List[float]]
    """Four [x, y] corner points, in the order returned by the OCR engine."""


@dataclass
class PageOCRResult:
    text: str
    average_confidence: Optional[float]
    blocks: List[TextBlockResult] = field(default_factory=list)


class OCREngine(Protocol):
    """Lightweight interface OCR engines (real or fake/test) must satisfy."""

    def run_page(self, image_path: str) -> PageOCRResult:
        ...


class PaddleOCREngine:
    """Adapter around PaddleOCR's PaddleOCR class."""

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:
            raise OCRDependencyError(
                "PaddleOCR is not installed or failed to import. "
                "Install it with 'pip install paddlepaddle paddleocr' to enable OCR."
            ) from exc

        try:
            # enable_mkldnn=False works around a NotImplementedError raised
            # by PaddlePaddle's oneDNN/PIR static-graph executor on some CPUs
            # ("ConvertPirAttribute2RuntimeAttribute not support
            # ArrayAttribute<DoubleAttribute>"). Plain CPU inference works
            # fine without oneDNN, at a modest performance cost.
            self._ocr = PaddleOCR(lang="en", enable_mkldnn=False)
        except Exception as exc:
            raise OCRDependencyError(f"PaddleOCR failed to initialize: {exc}") from exc

    def run_page(self, image_path: str) -> PageOCRResult:
        """Run OCR on a single page image using PaddleOCR's predict() pipeline.

        PaddleOCR 3.x returns one dict-like OCRResult per input image, with
        parallel lists "rec_texts", "rec_scores", and "rec_polys" (each poly
        being four [x, y] corner points) - this replaces the older ocr()/
        cls= API from PaddleOCR 2.x.
        """
        try:
            raw_results = self._ocr.predict(image_path)
        except Exception as exc:
            raise OCRDependencyError(
                f"PaddleOCR failed while processing {image_path}: {exc}"
            ) from exc

        blocks: List[TextBlockResult] = []
        line_texts: List[str] = []
        confidences: List[float] = []

        for page_result in raw_results or []:
            texts = page_result["rec_texts"]
            scores = page_result["rec_scores"]
            polys = page_result["rec_polys"]
            for text, score, poly in zip(texts, scores, polys):
                confidence = float(score) if score is not None else None
                box = [[float(point[0]), float(point[1])] for point in poly]
                blocks.append(TextBlockResult(text=text, confidence=confidence, box=box))
                line_texts.append(text)
                if confidence is not None:
                    confidences.append(confidence)

        average_confidence = sum(confidences) / len(confidences) if confidences else None
        return PageOCRResult(
            text="\n".join(line_texts),
            average_confidence=average_confidence,
            blocks=blocks,
        )


def get_default_engine() -> OCREngine:
    """Return the default OCR engine (PaddleOCR).

    Raises OCRDependencyError if the dependency is unavailable or fails to
    initialize - callers should catch this (or the broader exceptions it
    wraps) and surface a clear message instead of crashing.
    """
    return PaddleOCREngine()
