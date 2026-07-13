from abc import abstractmethod
from pydantic import BaseModel, Field
from typing import List, Optional

from selectolax.lexbor import LexborNode
from backend.managers.task_queue import ProgressFn


class ExtractedChapter(BaseModel):
    novel_id: int
    chapter_number: int
    title: str
    content_lines: list[str]
    source_url: str


class NovelMetadata(BaseModel):
    title: str
    author: List[str] = Field(default_factory=list)
    tags: Optional[List[str]] = None
    other_titles: Optional[List[str]] = None
    cover_image_url: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    total_chapters: int = 0
    chapter_urls: List[str] = Field(default_factory=list)


class BaseScraper(BaseModel):
    @property
    @abstractmethod
    def target_domain(self) -> str:
        """The base domain this scraper targers (e.g., 'wtr-lab.com')."""
        pass

    def can_handle(self, url: str) -> bool:
        """Determines if this module matches the income URL string pattern."""
        return self.target_domain in url.lower()

    @abstractmethod
    async def parse_metadata(
        self,
        source_url: str,
        network_mgr,
        *,
        report_progress: ProgressFn,
    ) -> NovelMetadata:
        """Parses the main landing page for novel info and the index table of contents."""
        pass

    @abstractmethod
    async def parse_chapter(
        self,
        novel_id: int,
        chapter_url: str,
        chapter_num: int,
        network_mgr,
        *,
        report_progress: ProgressFn,
    ) -> ExtractedChapter:
        """Parses an individual chapter page to extract headings and raw content text."""
        pass

    def is_node_hidden_by_css(self, node: LexborNode) -> bool:
        """
        Scans inline styles and known class signatures to detect hidden layout elements
        designed to intentionally distort text-to-speech engine outputs.
        """
        # 1. Catch explicit inline anti-scraper CSS definitions
        inline_style_optional = node.attributes.get("style", "")
        inline_style = inline_style_optional.lower() if inline_style_optional else None

        if inline_style and (
            "display:none" in inline_style
            or "visibility:hidden" in inline_style
            or "font-size:0" in inline_style
        ):
            return True

        # 2. Check for common randomized classes or known honey-pot text attributes
        # Add signatures commonly deployed to combat robotic parsers
        class_list_optional = node.attributes.get("class", "")
        class_list = class_list_optional.lower() if class_list_optional else None

        if class_list and (
            "anti-bot" in class_list
            or "hidden-text" in class_list
            or "spoiler" in class_list
        ):
            return True

        return False
