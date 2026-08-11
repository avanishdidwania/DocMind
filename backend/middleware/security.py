"""
Security Pipeline — Three classes, single responsibility each.

Flow: Raw Input → InputSanitizer → InjectionDetector → PII Masker → Clean Output

Each class does ONE thing:
- InputSanitizer: validates format (length, encoding, characters)
- InjectionDetector: detects manipulation attempts (pattern matching + scoring)
- PIIMasker: finds and redacts sensitive data (regex-based)

SecurityPipeline composes them into a single .process() call.
"""

import re
import logging
from dataclasses import dataclass, field

from models.schemas import SecurityResult, SecurityVerdict

logger = logging.getLogger(__name__)


# ─── Input Sanitizer ────────────────────────────────────────────────────────


class InputSanitizer:
    """
    Basic input hygiene. Catches malformed input before deeper checks run.

    This is NOT about malicious intent (that's InjectionDetector).
    This is about garbage input that could crash downstream code.
    """

    def __init__(self, max_length: int = 10000):
        self.max_length = max_length

    def clean(self, raw_input: str) -> str:
        """
        Validate and clean raw input.
        Raises ValueError if input is fundamentally invalid.
        """
        # Reject empty/whitespace-only
        if not raw_input or not raw_input.strip():
            raise ValueError("Input cannot be empty")

        # Reject if too long (prevents token abuse)
        if len(raw_input) > self.max_length:
            raise ValueError(
                f"Input exceeds maximum length ({len(raw_input)} > {self.max_length})"
            )

        # Strip null bytes and control characters (except newlines/tabs)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw_input)

        # Normalize whitespace (collapse multiple spaces, strip edges)
        cleaned = cleaned.strip()

        return cleaned


# ─── Injection Detector ─────────────────────────────────────────────────────


@dataclass
class InjectionResult:
    """Result of injection analysis."""
    is_blocked: bool
    score: float  # 0.0 = safe, 1.0 = definite injection
    matched_patterns: list[str] = field(default_factory=list)


class InjectionDetector:
    """
    Detects prompt injection attempts using pattern matching and scoring.

    Not perfect (injection detection never is), but catches obvious attacks.
    Defense in depth — this is ONE layer, combined with system prompt design
    and output validation.
    """

    # Patterns with weights (higher weight = stronger signal)
    INJECTION_PATTERNS: list[tuple[str, float]] = [
        # Direct instruction override
        (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|context)", 0.9),
        (r"disregard\s+(all\s+)?(previous|prior|above|the)", 0.9),
        (r"forget\s+(everything|all|your)\s+(before|about|instructions)", 0.85),

        # Role manipulation
        (r"you\s+are\s+now\s+(a|an|my)", 0.8),
        (r"act\s+as\s+if\s+you\s+(have|are|were)", 0.75),
        (r"pretend\s+(you|to\s+be)", 0.7),
        (r"from\s+now\s+on\s+you\s+(are|will)", 0.8),

        # System prompt extraction
        (r"(repeat|show|reveal|display)\s+(your|the)\s+(system\s+)?(prompt|instructions)", 0.95),
        (r"what\s+(are|is)\s+your\s+(system\s+)?(instructions|prompt|rules)", 0.7),

        # Jailbreak keywords
        (r"\bjailbreak\b", 0.85),
        (r"\bdan\s+mode\b", 0.9),
        (r"do\s+anything\s+now", 0.9),

        # Delimiter injection (trying to close the prompt and inject new instructions)
        (r"```\s*(system|assistant|user)", 0.8),
        (r"\[INST\]|\[\/INST\]|<\|im_start\|>|<\|im_end\|>", 0.85),

        # Encoded/obfuscated attempts
        (r"base64\s*decode", 0.6),
        (r"eval\s*\(", 0.7),
    ]

    def __init__(self, threshold: float = 0.7):
        """
        Args:
            threshold: Score above which input is BLOCKED (0.0-1.0).
                       Lower = stricter, more false positives.
                       Higher = more permissive, might miss attacks.
        """
        self.threshold = threshold
        # Pre-compile regex patterns for performance
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), weight)
            for pattern, weight in self.INJECTION_PATTERNS
        ]

    def detect(self, text: str) -> InjectionResult:
        """
        Analyze input for injection attempts.
        Returns score (0-1) and whether it should be blocked.
        """
        matched_patterns = []
        max_score = 0.0

        for compiled_regex, weight in self._compiled_patterns:
            if compiled_regex.search(text):
                matched_patterns.append(compiled_regex.pattern)
                max_score = max(max_score, weight)

        # Multiple weak signals compound
        if len(matched_patterns) >= 2 and max_score < self.threshold:
            max_score = min(max_score + 0.15, 1.0)

        is_blocked = max_score >= self.threshold

        if is_blocked:
            logger.warning(
                "Injection detected",
                extra={
                    "score": max_score,
                    "patterns_matched": len(matched_patterns),
                    "action": "blocked",
                },
            )

        return InjectionResult(
            is_blocked=is_blocked,
            score=max_score,
            matched_patterns=matched_patterns,
        )


# ─── PII Masker ─────────────────────────────────────────────────────────────


class PIIMasker:
    """
    Detects and masks Personally Identifiable Information.

    The LLM sees [REDACTED_*] placeholders instead of real data.
    This protects users even if the LLM provider's logs are breached.
    """

    # (pattern, replacement_label)
    PII_PATTERNS: list[tuple[str, str]] = [
        # Credit card numbers (4 groups of 4 digits)
        (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "CREDIT_CARD"),

        # Social Security Numbers (US)
        (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),

        # Email addresses
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "EMAIL"),

        # Phone numbers (various formats)
        (r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "PHONE"),

        # IP addresses
        (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP_ADDRESS"),

        # Aadhaar numbers (India — 12 digits with optional spaces)
        (r"\b\d{4}\s?\d{4}\s?\d{4}\b", "AADHAAR"),

        # PAN card (India — ABCDE1234F format)
        (r"\b[A-Z]{5}\d{4}[A-Z]\b", "PAN_CARD"),
    ]

    def __init__(self):
        self._compiled_patterns = [
            (re.compile(pattern), label)
            for pattern, label in self.PII_PATTERNS
        ]
        self.detected_types: list[str] = []

    def mask(self, text: str) -> str:
        """
        Find and replace PII with [REDACTED_TYPE] placeholders.
        Returns the masked text. Call .detected_types for what was found.
        """
        self.detected_types = []
        masked = text

        for compiled_regex, label in self._compiled_patterns:
            if compiled_regex.search(masked):
                self.detected_types.append(label)
                masked = compiled_regex.sub(f"[REDACTED_{label}]", masked)

        if self.detected_types:
            logger.info(
                "PII masked",
                extra={"pii_types": self.detected_types, "count": len(self.detected_types)},
            )

        return masked


# ─── Security Pipeline (Composition) ────────────────────────────────────────


class SecurityPipeline:
    """
    Composes all three security components into a single .process() call.

    Order matters:
    1. Sanitize first (reject garbage before expensive checks)
    2. Injection detection (block attacks before masking)
    3. PII masking (clean data for legitimate requests)
    """

    def __init__(self, max_input_length: int = 10000, injection_threshold: float = 0.7):
        self.sanitizer = InputSanitizer(max_length=max_input_length)
        self.injection_detector = InjectionDetector(threshold=injection_threshold)
        self.pii_masker = PIIMasker()

    def process(self, raw_input: str) -> SecurityResult:
        """
        Run the full security pipeline on raw user input.

        Returns SecurityResult with:
        - verdict: safe / suspicious / blocked
        - cleaned_input: sanitized + PII-masked text (only if not blocked)
        - pii_detected: list of PII types found
        - injection_score: 0.0 - 1.0
        - reason: why it was blocked (if blocked)
        """
        # Step 1: Sanitize
        try:
            sanitized = self.sanitizer.clean(raw_input)
        except ValueError as e:
            return SecurityResult(
                verdict=SecurityVerdict.blocked,
                reason=f"Input validation failed: {str(e)}",
                injection_score=0.0,
            )

        # Step 2: Injection detection
        injection_result = self.injection_detector.detect(sanitized)

        if injection_result.is_blocked:
            return SecurityResult(
                verdict=SecurityVerdict.blocked,
                injection_score=injection_result.score,
                reason="Potential prompt injection detected",
            )

        # Step 3: PII masking (only for non-blocked requests)
        masked_input = self.pii_masker.mask(sanitized)

        # Determine verdict
        if injection_result.score > 0.3:
            verdict = SecurityVerdict.suspicious
        else:
            verdict = SecurityVerdict.safe

        return SecurityResult(
            verdict=verdict,
            cleaned_input=masked_input,
            pii_detected=self.pii_masker.detected_types,
            injection_score=injection_result.score,
        )
