from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import List, Optional


class ExtractedChapter(BaseModel):
    novel_id: int
    chapter_number: int
    title: str
    content: str
    source_url: str


class NovelMetadata(BaseModel):
    title: str
    author: str
    cover_image_url: Optional[str] = None
    summary: Optional[str] = None
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
    def parse_metadata(self, html_content: str, source_url: str) -> NovelMetadata:
        """Parses the main landing page for novel info and the index table of contents."""
        pass

    @abstractmethod
    def parse_chapter(
        self, html_content: str, chapter_url: str, chapter_num: int
    ) -> ExtractedChapter:
        """Parses an individual chapter page to extract headings and raw content text."""
        pass
