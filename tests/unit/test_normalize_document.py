"""Tests para el documento normalizado."""

import pytest

from app.application.pipeline.normalize_document import (
    ExtractionSource,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
)


class TestNormalizedBlock:
    def test_creation(self):
        block = NormalizedBlock(
            text="Hello world",
            bbox=(10, 20, 100, 50),
            page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        assert block.text == "Hello world"
        assert block.bbox == (10, 20, 100, 50)
        assert block.page == 1
        assert block.source == ExtractionSource.DIGITAL_TEXT

    def test_immutable(self):
        block = NormalizedBlock(
            text="x", bbox=(0, 0, 1, 1), page=1, source=ExtractionSource.OCR
        )
        with pytest.raises((TypeError, AttributeError)):
            block.text = "y"


class TestNormalizedPage:
    def test_full_text(self):
        block1 = NormalizedBlock(
            text="Line 1", bbox=(0, 0, 100, 10), page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        block2 = NormalizedBlock(
            text="Line 2", bbox=(0, 10, 100, 20), page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        page = NormalizedPage(page_number=1, blocks=[block1, block2])
        assert page.full_text == "Line 1\nLine 2"

    def test_full_text_empty(self):
        page = NormalizedPage(page_number=1, blocks=[])
        assert page.full_text == ""


class TestNormalizedDocument:
    def test_all_blocks(self):
        block1 = NormalizedBlock(
            text="Page 1 text", bbox=(0, 0, 100, 10), page=1,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        block2 = NormalizedBlock(
            text="Page 2 text", bbox=(0, 0, 100, 10), page=2,
            source=ExtractionSource.DIGITAL_TEXT,
        )
        doc = NormalizedDocument(pages=[
            NormalizedPage(page_number=1, blocks=[block1]),
            NormalizedPage(page_number=2, blocks=[block2]),
        ])
        assert len(doc.all_blocks) == 2
        assert doc.all_blocks[0].page == 1
        assert doc.all_blocks[1].page == 2

    def test_full_text(self):
        page1 = NormalizedPage(
            page_number=1,
            blocks=[
                NormalizedBlock(
                    text="Hello", bbox=(0, 0, 100, 10), page=1,
                    source=ExtractionSource.DIGITAL_TEXT,
                ),
            ],
        )
        page2 = NormalizedPage(
            page_number=2,
            blocks=[
                NormalizedBlock(
                    text="World", bbox=(0, 0, 100, 10), page=2,
                    source=ExtractionSource.DIGITAL_TEXT,
                ),
            ],
        )
        doc = NormalizedDocument(pages=[page1, page2])
        assert "Hello" in doc.full_text
        assert "World" in doc.full_text

    def test_default_source(self):
        doc = NormalizedDocument()
        assert doc.source == ExtractionSource.DIGITAL_TEXT

    def test_empty_pages(self):
        doc = NormalizedDocument(pages=[])
        assert doc.all_blocks == []
        assert doc.full_text == ""