export interface NovelMetadata {
  title: string;
  novel_id: string;
  author: string[];
  tags: string[] | null;
  other_titles: string[] | null;
  cover_image_url: string | null;
  summary: string | null;
  status: string | null;
  total_chapters: number;
  chapter_urls: string[];
}

export interface ExtractedChapter {
  novel_id: string;
  chapter_number: number;
  title: string;
  content: string;
  source_url: string;
}
