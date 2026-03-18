"""
Input Sanitization & Validation

Advanced input validation for LLM prompts with encoding attack detection,
Unicode normalization, repetition attacks, and token limit enforcement.
Complements the existing core/sanitizer.py module.
"""

import base64
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Maximum defaults
DEFAULT_MAX_LENGTH = 100_000  # characters
DEFAULT_MAX_TOKENS = 8_192   # estimated tokens
REPETITION_THRESHOLD = 0.4   # 40% repeated content triggers warning


@dataclass
class ValidationResult:
    """Input validation result."""
    is_valid: bool
    sanitized_text: str
    warnings: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None


class InputValidator:
    """
    Advanced input validation for AI agent prompts.

    Checks:
    - Length and token limits
    - Encoding attacks (base64/hex obfuscation)
    - Unicode normalization (homoglyphs, zero-width chars)
    - Control character removal
    - Repetition/flooding attacks
    """

    # Zero-width and invisible Unicode characters
    INVISIBLE_CHARS = re.compile(
        r'[\u200b-\u200f'   # zero-width space, joiners, marks
        r'\u2028-\u202f'    # line/paragraph separators, embeddings
        r'\u2060-\u206f'    # word joiner, invisible operators
        r'\ufeff'           # BOM
        r'\ufff9-\ufffb]'   # interlinear annotations
    )

    # Homoglyph map: visually similar characters → ASCII equivalents
    HOMOGLYPH_MAP = str.maketrans({
        '\u0410': 'A', '\u0412': 'B', '\u0421': 'C', '\u0415': 'E',  # Cyrillic
        '\u041d': 'H', '\u041a': 'K', '\u041c': 'M', '\u041e': 'O',
        '\u0420': 'P', '\u0422': 'T', '\u0425': 'X',
        '\u0430': 'a', '\u0435': 'e', '\u043e': 'o', '\u0440': 'p',
        '\u0441': 'c', '\u0443': 'y', '\u0445': 'x',
        '\uff21': 'A', '\uff22': 'B', '\uff23': 'C',  # Fullwidth Latin
        '\uff41': 'a', '\uff42': 'b', '\uff43': 'c',
        '\u2018': "'", '\u2019': "'",  # Smart quotes
        '\u201c': '"', '\u201d': '"',
    })

    # Base64-encoded content pattern
    BASE64_PATTERN = re.compile(
        r'(?:^|[\s:=])([A-Za-z0-9+/]{40,}={0,2})(?:$|[\s])',
        re.MULTILINE,
    )

    # Hex-encoded content pattern
    HEX_PATTERN = re.compile(
        r'(?:\\x[0-9a-fA-F]{2}){4,}|'
        r'(?:0x[0-9a-fA-F]{2}\s*){4,}',
    )

    # Control characters (except \t, \n, \r)
    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

    def __init__(
        self,
        max_length: int = DEFAULT_MAX_LENGTH,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.max_length = max_length
        self.max_tokens = max_tokens

    def validate(self, text: str) -> ValidationResult:
        """
        Validate and sanitize input text.

        Returns a ValidationResult with is_valid=False if the input
        should be rejected entirely, or is_valid=True with sanitized_text
        and any warnings.
        """
        if not text or not text.strip():
            return ValidationResult(
                is_valid=False,
                sanitized_text="",
                blocked_reason="Empty input",
            )

        warnings: List[str] = []
        sanitized = text

        # 1. Length check (hard block)
        if len(sanitized) > self.max_length:
            return ValidationResult(
                is_valid=False,
                sanitized_text="",
                blocked_reason=f"Input exceeds maximum length of {self.max_length} characters ({len(sanitized)} given)",
            )

        # 2. Estimated token check (hard block)
        estimated_tokens = len(sanitized.split())
        if estimated_tokens > self.max_tokens:
            return ValidationResult(
                is_valid=False,
                sanitized_text="",
                blocked_reason=f"Input exceeds estimated token limit of {self.max_tokens} (~{estimated_tokens} tokens)",
            )

        # 3. Control character removal
        cleaned = self.CONTROL_CHARS.sub('', sanitized)
        if cleaned != sanitized:
            warnings.append("Control characters removed")
            sanitized = cleaned

        # 4. Zero-width / invisible character removal
        cleaned = self.INVISIBLE_CHARS.sub('', sanitized)
        if cleaned != sanitized:
            warnings.append("Invisible Unicode characters removed")
            sanitized = cleaned

        # 5. Homoglyph normalization
        normalized = sanitized.translate(self.HOMOGLYPH_MAP)
        if normalized != sanitized:
            warnings.append("Homoglyph characters normalized to ASCII equivalents")
            sanitized = normalized

        # 6. Unicode NFKC normalization
        nfkc = unicodedata.normalize('NFKC', sanitized)
        if nfkc != sanitized:
            warnings.append("Unicode NFKC normalization applied")
            sanitized = nfkc

        # 7. Encoding attack detection (warn but don't block)
        encoding_warning = self._check_encoding_attacks(sanitized)
        if encoding_warning:
            warnings.append(encoding_warning)

        # 8. Repetition attack detection
        repetition_warning = self._check_repetition(sanitized)
        if repetition_warning:
            warnings.append(repetition_warning)

        # 9. Normalize whitespace
        sanitized = re.sub(r'\n{3,}', '\n\n', sanitized)
        sanitized = re.sub(r' {3,}', ' ', sanitized)
        sanitized = sanitized.strip()

        if warnings:
            logger.warning(f"InputValidator warnings: {warnings}")

        return ValidationResult(
            is_valid=True,
            sanitized_text=sanitized,
            warnings=warnings,
        )

    def _check_encoding_attacks(self, text: str) -> Optional[str]:
        """Detect base64 or hex-encoded payloads that may hide malicious content."""
        # Check for base64 blocks
        base64_matches = self.BASE64_PATTERN.findall(text)
        for match in base64_matches:
            try:
                decoded = base64.b64decode(match).decode('utf-8', errors='ignore')
                # Check if decoded content contains suspicious patterns
                suspicious_keywords = [
                    'ignore', 'system', 'prompt', 'override',
                    'instruction', 'jailbreak', 'bypass',
                ]
                if any(kw in decoded.lower() for kw in suspicious_keywords):
                    return f"Suspicious base64-encoded content detected (decoded contains attack patterns)"
            except Exception:
                pass

        # Check for hex-encoded sequences
        if self.HEX_PATTERN.search(text):
            return "Hex-encoded sequences detected in input"

        return None

    def _check_repetition(self, text: str) -> Optional[str]:
        """Detect repetition/flooding attacks."""
        if len(text) < 100:
            return None

        # Check for repeated words
        words = text.lower().split()
        if not words:
            return None

        # Count most frequent word
        word_counts: dict = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1

        if word_counts:
            max_count = max(word_counts.values())
            ratio = max_count / len(words)
            if ratio > REPETITION_THRESHOLD and max_count > 10:
                return f"Repetition attack suspected: single word repeated {max_count}/{len(words)} times ({ratio:.0%})"

        # Check for repeated character sequences
        if len(text) > 200:
            chunk_size = 50
            chunks = [text[i:i+chunk_size] for i in range(0, len(text) - chunk_size, chunk_size)]
            if chunks:
                unique_chunks = set(chunks)
                if len(unique_chunks) <= len(chunks) * 0.3:
                    return "Repeated content pattern detected (possible flooding attack)"

        return None
