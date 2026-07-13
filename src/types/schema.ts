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
  sourceUrl: string;
  title: string | null;
  author: string[];
  otherTitles: string[];
  tags: string[];
  summary: string | null;
  status: string | null;
  coverImageUrl: string | null;
  coverImagePath: string | null;
  totalChapters: number;
  downloadedChapters: number;
  scrapeState: "pending" | "discovering" | "downloading" | "complete" | "error";
  addedAt: string;
  updatedAt: string;
};

export type Chapter = {
  novelId: number;
  chapterNumber: number;
  title: string | null;
  sourceUrl: string | null;
  contentPath: string | null;
  downloadedAt: string | null;
};
