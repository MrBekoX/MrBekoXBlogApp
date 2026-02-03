"""Markdown-aware text chunking for RAG."""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Chunking configuration
DEFAULT_CHUNK_SIZE = 500  # tokens (approximate)
DEFAULT_CHUNK_OVERLAP = 50  # tokens
CHARS_PER_TOKEN = 4  # Rough approximation for Turkish/English


@dataclass
class TextChunk:
    """A chunk of text with metadata."""

    content: str
    chunk_index: int
    section_title: Optional[str] = None
    start_char: int = 0
    end_char: int = 0

    @property
    def token_count(self) -> int:
        """Approximate token count."""
        return len(self.content) // CHARS_PER_TOKEN


class TextChunker:
    """
    Markdown-aware text chunker.

    Features:
    - Preserves code blocks (doesn't split in the middle)
    - Respects heading boundaries
    - Configurable chunk size and overlap
    - Maintains section context
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    ):
        self._chunk_size_chars = chunk_size * CHARS_PER_TOKEN
        self._chunk_overlap_chars = chunk_overlap * CHARS_PER_TOKEN

    def chunk(self, text: str, preserve_code_blocks: bool = True) -> list[TextChunk]:
        """
        Split text into chunks.

        Args:
            text: The text to chunk
            preserve_code_blocks: If True, don't split code blocks

        Returns:
            List of TextChunk objects
        """
        logger.info(f"Starting chunking process for text length: {len(text)}")
        
        if not text or not text.strip():
            logger.warning("Empty text provided to chunker")
            return []

        logger.debug(f"Text preview: {text[:200]}...")

        # Extract and protect code blocks if needed
        code_blocks: dict[str, str] = {}
        if preserve_code_blocks:
            text, code_blocks = self._protect_code_blocks(text)

        # Split by sections (headings)
        sections = self._split_by_sections(text)
        logger.info(f"Split into {len(sections)} sections")

        # Chunk each section
        chunks: list[TextChunk] = []
        chunk_index = 0

        for i, (section_title, section_content) in enumerate(sections):
            logger.debug(f"Processing section {i}: {section_title} (length: {len(section_content)})")
            section_chunks = self._chunk_section(
                section_content,
                section_title,
                chunk_index
            )
            chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        # Restore code blocks
        if code_blocks:
            for chunk in chunks:
                chunk.content = self._restore_code_blocks(chunk.content, code_blocks)

        logger.info(f"Chunking completed: {len(chunks)} chunks created")
        return chunks

    def _protect_code_blocks(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace code blocks with placeholders."""
        code_blocks = {}
        counter = 0

        def replace_code(match: re.Match) -> str:
            nonlocal counter
            placeholder = f"__CODE_BLOCK_{counter}__"
            code_blocks[placeholder] = match.group(0)
            counter += 1
            return placeholder

        # Match fenced code blocks (```...```)
        pattern = r'```[\s\S]*?```'
        text = re.sub(pattern, replace_code, text)

        # Match inline code (`...`)
        pattern = r'`[^`\n]+`'
        text = re.sub(pattern, replace_code, text)

        return text, code_blocks

    def _restore_code_blocks(self, text: str, code_blocks: dict[str, str]) -> str:
        """Restore code blocks from placeholders."""
        for placeholder, code in code_blocks.items():
            text = text.replace(placeholder, code)
        return text

    def _split_by_sections(self, text: str) -> list[tuple[Optional[str], str]]:
        """
        Split text by markdown headings.

        Returns:
            List of (section_title, section_content) tuples
        """
        # Pattern to match markdown headings
        heading_pattern = r'^(#{1,6})\s+(.+)$'

        lines = text.split('\n')
        sections: list[tuple[Optional[str], str]] = []
        current_title: Optional[str] = None
        current_content: list[str] = []

        for line in lines:
            match = re.match(heading_pattern, line)
            if match:
                # Save previous section if exists
                if current_content or current_title:
                    sections.append((current_title, '\n'.join(current_content)))

                # Start new section
                current_title = match.group(2).strip()
                current_content = []
            else:
                current_content.append(line)

        # Don't forget the last section
        if current_content or current_title:
            sections.append((current_title, '\n'.join(current_content)))

        # If no headings found, treat entire text as one section
        if not sections:
            sections = [(None, text)]

        return sections

    def _chunk_section(
        self,
        content: str,
        section_title: Optional[str],
        start_index: int
    ) -> list[TextChunk]:
        """
        Chunk a single section.

        Uses sentence-aware splitting to avoid breaking sentences.
        """
        if not content.strip():
            return []

        chunks: list[TextChunk] = []
        text = content.strip()

        # If content is smaller than chunk size, return as single chunk
        if len(text) <= self._chunk_size_chars:
            return [TextChunk(
                content=text,
                chunk_index=start_index,
                section_title=section_title,
                start_char=0,
                end_char=len(text)
            )]

        # Split by paragraphs first (double newline)
        paragraphs = re.split(r'\n\n+', text)

        current_chunk: list[str] = []
        current_size = 0
        chunk_index = start_index
        char_offset = 0

        for para in paragraphs:
            para_size = len(para)

            # If single paragraph is larger than chunk size, split by sentences
            if para_size > self._chunk_size_chars:
                # Save current chunk if exists
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_content,
                        chunk_index=chunk_index,
                        section_title=section_title,
                        start_char=char_offset,
                        end_char=char_offset + len(chunk_content)
                    ))
                    chunk_index += 1
                    char_offset += len(chunk_content) + 2  # +2 for \n\n
                    current_chunk = []
                    current_size = 0

                # Split large paragraph by sentences
                sentence_chunks = self._split_by_sentences(para)
                for sent_chunk in sentence_chunks:
                    chunks.append(TextChunk(
                        content=sent_chunk,
                        chunk_index=chunk_index,
                        section_title=section_title,
                        start_char=char_offset,
                        end_char=char_offset + len(sent_chunk)
                    ))
                    chunk_index += 1
                    char_offset += len(sent_chunk) + 2

            elif current_size + para_size + 2 > self._chunk_size_chars:
                # Current chunk is full, save it and start new one
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunks.append(TextChunk(
                        content=chunk_content,
                        chunk_index=chunk_index,
                        section_title=section_title,
                        start_char=char_offset,
                        end_char=char_offset + len(chunk_content)
                    ))
                    chunk_index += 1

                    # Apply overlap - take last paragraph(s) for context
                    overlap_content = self._get_overlap_content(current_chunk)
                    char_offset += len(chunk_content) + 2 - len(overlap_content)
                    current_chunk = [overlap_content] if overlap_content else []
                    current_size = len(overlap_content) if overlap_content else 0

                current_chunk.append(para)
                current_size += para_size + 2
            else:
                current_chunk.append(para)
                current_size += para_size + 2

        # Don't forget the last chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            chunks.append(TextChunk(
                content=chunk_content,
                chunk_index=chunk_index,
                section_title=section_title,
                start_char=char_offset,
                end_char=char_offset + len(chunk_content)
            ))

        return chunks

    def _split_by_sentences(self, text: str) -> list[str]:
        """Split text by sentences for large paragraphs."""
        # Simple sentence splitting - handles Turkish and English
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for sentence in sentences:
            sent_size = len(sentence)

            if current_size + sent_size + 1 > self._chunk_size_chars and current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = []
                current_size = 0

            current_chunk.append(sentence)
            current_size += sent_size + 1

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks

    def _get_overlap_content(self, paragraphs: list[str]) -> str:
        """Get content for overlap from the end of current chunk."""
        if not paragraphs:
            return ""

        # Take content from the end up to overlap size
        overlap_parts: list[str] = []
        total_size = 0

        for para in reversed(paragraphs):
            if total_size + len(para) > self._chunk_overlap_chars:
                break
            overlap_parts.insert(0, para)
            total_size += len(para) + 2

        return '\n\n'.join(overlap_parts) if overlap_parts else ""


# Global singleton instance
text_chunker = TextChunker()
