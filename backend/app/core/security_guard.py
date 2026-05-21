"""
Security guard — validates and sanitizes user inputs before they reach the LLM.

What we protect against:
  1. Prompt injection  — attacker tries to override system instructions
  2. Jailbreaks        — attacker tries to bypass safety rules
  3. Excessive length  — long inputs inflate token cost and slow responses
  4. Role confusion    — attacker embeds fake assistant turns in their message

This is a heuristic layer, not a perfect filter. Defense in depth:
  - This guard = first line (fast, cheap)
  - System prompt framing = second line (LLM-level)
  - Output validation = third line (check answer before returning)

None of these is 100%. They raise the cost of attack and catch the common cases.
"""

import re
from fastapi import HTTPException, status


# ── Configuration ─────────────────────────────────────────────────────────────

MAX_QUESTION_LENGTH = 2000   # chars (~500 tokens)
MAX_DOCUMENT_NAME_LENGTH = 255

# Patterns that strongly suggest prompt injection attempts.
# Each tuple: (compiled regex, short description for logging)
_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Classic instruction override attempts
    (re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.I),
     "ignore-previous-instructions"),
    (re.compile(r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)", re.I),
     "disregard-previous"),
    (re.compile(r"forget\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|context)", re.I),
     "forget-instructions"),

    # System prompt extraction attempts
    (re.compile(r"(repeat|print|output|show|reveal|display)\s+(your\s+)?(system\s+prompt|instructions?|prompt)", re.I),
     "system-prompt-extraction"),
    (re.compile(r"what\s+(are\s+your|is\s+your)\s+(system\s+prompt|instructions?|rules?)", re.I),
     "instructions-inquiry"),

    # Role override attempts
    (re.compile(r"\bact\s+as\s+(a\s+)?(different|new|another|unrestricted|evil|dan)\b", re.I),
     "role-override"),
    (re.compile(r"\byou\s+are\s+now\s+(a\s+)?(different|new|another|unrestricted)", re.I),
     "you-are-now"),
    (re.compile(r"\bpretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|unrestricted|evil|hacker)", re.I),
     "pretend-override"),

    # DAN / jailbreak patterns
    (re.compile(r"\b(do\s+anything\s+now|DAN\b|jailbreak|bypass\s+(safety|filters?|restrictions?))", re.I),
     "jailbreak-keywords"),

    # Fake delimiter injection (trying to inject new <system> blocks)
    (re.compile(r"<\s*(system|instructions?|prompt)\s*>", re.I),
     "fake-system-tag"),

    # Indirect injection via "translate/summarize this:" then injected content
    (re.compile(r"(translate|summarize|paraphrase)\s*[:\-]?\s*ignore\s+", re.I),
     "indirect-injection"),
]


class SecurityGuard:

    def validate_question(self, question: str) -> str:
        """
        Validate and sanitize a user question.
        Returns the (possibly trimmed) question on success.
        Raises HTTP 400 on security violations.
        """
        if not question or not question.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question cannot be empty.",
            )

        # Length check — protects against token stuffing
        if len(question) > MAX_QUESTION_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Question too long. Maximum {MAX_QUESTION_LENGTH} characters.",
            )

        # Prompt injection detection
        for pattern, label in _INJECTION_PATTERNS:
            if pattern.search(question):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Your message contains content that cannot be processed. "
                           "Please ask a question about your documents.",
                )

        # Strip null bytes and control characters (keep newlines for multi-line questions)
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", question)

        return sanitized.strip()

    def validate_file_bytes(self, data: bytes, declared_extension: str) -> None:
        """
        Validate file magic bytes match the declared extension.
        Prevents MIME-type spoofing (renaming a .exe to .pdf).
        Raises HTTP 400 on mismatch.
        """
        # Magic byte signatures for allowed file types
        # Format: extension → list of (offset, bytes) pairs that must match
        _MAGIC: dict[str, list[tuple[int, bytes]]] = {
            ".pdf":  [(0, b"%PDF")],
            ".docx": [(0, b"PK\x03\x04")],   # DOCX is a ZIP container
            ".txt":  [],                        # no reliable magic bytes for plain text
            ".md":   [],                        # no reliable magic bytes for markdown
        }

        ext = declared_extension.lower()
        checks = _MAGIC.get(ext, [])

        for offset, magic in checks:
            if len(data) < offset + len(magic):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File content does not match declared type ({ext}).",
                )
            if data[offset: offset + len(magic)] != magic:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File content does not match declared type ({ext}). "
                           "Possible MIME type spoofing detected.",
                )

    def validate_url(self, url: str) -> None:
        """
        Block URLs that target internal/private networks (SSRF protection).
        Raises HTTP 400 for suspicious URLs.
        """
        # Block common internal network ranges
        _BLOCKED = re.compile(
            r"https?://(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.0\.0\.0)",
            re.I,
        )
        if _BLOCKED.match(url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URLs pointing to private/internal networks are not allowed.",
            )


security_guard = SecurityGuard()
