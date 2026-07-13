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

export type Novel = {
  id: number;
  source_url: string;
  title: string | null;
  author: string[];
  other_titles: string[];
  tags: string[];
  summary: string | null;
  status: string | null;
  cover_image_url: string | null;
  cover_image_path: string | null;
  total_chapters: number;
  downloaded_chapters: number;
  scrape_state: "pending" | "discovering" | "downloading" | "complete" | "error";
  added_at: string;
  updated_at: string;
};

export type Chapter = {
  novel_id: number;
  chapter_number: number;
  title: string | null;
  source_url: string | null;
  content_path: string | null;
  downloaded_at: string | null;
};
