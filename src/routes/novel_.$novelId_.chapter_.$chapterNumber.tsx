// routes/novel.$novelId.chapter.$chapterNumber.tsx
//
// The reader. Deliberately a different visual register from the rest of
// the app: long-form reading wants a warmer, dimmer surface than the
// operational slate-950 shell, generous serif type, and a narrow measure
// (~65ch) — the goal is something closer to Apple Books/Kindle than a
// dashboard. Preloads the next 5 chapters' content in the background so
// tapping "Next" feels instant instead of round-tripping to Python each
// time.

import { useEffect, useMemo } from "react";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/task-manager";
import { useNovelQuery, useNovelChaptersQuery, useChapterContentQuery, queryKeys } from "@/queries";

export const Route = createFileRoute("/novel_/$novelId_/chapter_/$chapterNumber")({
    component: ReaderPage,
});

const PRELOAD_AHEAD = 5;

function ReaderPage() {
    const { novelId, chapterNumber } = Route.useParams();
    const novelIdNum = Number(novelId);
    const chapterNum = Number(chapterNumber);
    const navigate = useNavigate();
    const queryClient = useQueryClient();

    const { data: novel } = useNovelQuery(novelIdNum);
    const { data: chapters = [] } = useNovelChaptersQuery(novelIdNum);
    const { data: content, isLoading, isError, error } = useChapterContentQuery(novelIdNum, chapterNum);

    const sortedNumbers = useMemo(
        () => chapters.map((c) => c.chapter_number).sort((a, b) => a - b),
        [chapters]
    );
    const currentIndex = sortedNumbers.indexOf(chapterNum);
    const prevNumber = currentIndex > 0 ? sortedNumbers[currentIndex - 1] : null;
    const nextNumber =
        currentIndex >= 0 && currentIndex < sortedNumbers.length - 1 ? sortedNumbers[currentIndex + 1] : null;
    const currentChapter = chapters.find((c) => c.chapter_number === chapterNum);

    // Preload the next 5 downloaded chapters' content in the background.
    // staleTime: Infinity on the query itself means once prefetched, it's
    // never silently refetched — this just warms the cache ahead of time.
    useEffect(() => {
        if (currentIndex < 0) return;
        const upcoming = sortedNumbers.slice(currentIndex + 1, currentIndex + 1 + PRELOAD_AHEAD);
        for (const num of upcoming) {
            queryClient.prefetchQuery({
                queryKey: queryKeys.chapterContent(novelIdNum, num),
                queryFn: () => api.getChapterContent(novelIdNum, num),
                staleTime: Infinity,
            });
        }
    }, [currentIndex, sortedNumbers, novelIdNum, queryClient]);

    function goTo(num: number | null) {
        if (num === null) return;
        navigate({ to: "/novel/$novelId/chapter/$chapterNumber", params: { novelId, chapterNumber: String(num) } });
    }

    // left/right arrow key navigation — expected in any reader
    useEffect(() => {
        function onKey(e: KeyboardEvent) {
            if (e.key === "ArrowRight") goTo(nextNumber);
            else if (e.key === "ArrowLeft") goTo(prevNumber);
        }
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nextNumber, prevNumber]);

    // Split on blank-line boundaries first (the common case for scraped
    // text), falling back to single newlines — either way, empty
    // fragments from repeated whitespace are dropped.
    const paragraphs = useMemo(() => {
        if (!content) return [];
        const byBlankLine = content.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
        if (byBlankLine.length > 1) return byBlankLine;
        return content.split(/\n/).map((p) => p.trim()).filter(Boolean);
    }, [content]);

    return (
        <div className="min-h-screen bg-[#161a20] text-[#e8e3d8]">
            <header className="sticky top-0 z-10 border-b border-white/5 bg-[#161a20]/95 px-6 py-3 backdrop-blur">
                <div className="mx-auto flex max-w-2xl items-center justify-between gap-4">
                    <Link
                        to="/novel/$novelId"
                        params={{ novelId }}
                        className="truncate text-xs text-[#8a8578] transition hover:text-[#e8e3d8]"
                    >
                        ← {novel?.title ?? "Back to novel"}
                    </Link>
                    <span className="shrink-0 text-xs text-[#8a8578]">
                        Chapter {chapterNum}
                        {sortedNumbers.length > 0 && ` of ${sortedNumbers.length}`}
                    </span>
                </div>
            </header>

            <main className="mx-auto max-w-2xl px-6 py-10">
                {isLoading ? (
                    <p className="text-sm text-[#8a8578]">Loading…</p>
                ) : isError ? (
                    <p className="text-sm text-rose-400">
                        {error instanceof Error ? error.message : "Couldn't load this chapter."}
                    </p>
                ) : (
                    <article>
                        <h1 className="mb-8 font-serif text-2xl font-semibold text-[#e8e3d8]">
                            {currentChapter?.title ?? `Chapter ${chapterNum}`}
                        </h1>
                        <div className="space-y-5 font-serif text-[1.0625rem] leading-[1.85] text-[#d8d3c6]">
                            {paragraphs.map((p, i) => (
                                <p key={i}>{p}</p>
                            ))}
                        </div>
                    </article>
                )}

                <nav className="mt-14 flex items-center justify-between border-t border-white/5 pt-6">
                    <button
                        type="button"
                        disabled={prevNumber === null}
                        onClick={() => goTo(prevNumber)}
                        className="rounded-md px-3 py-2 text-sm text-[#c9c4b7] transition hover:bg-white/5 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
                    >
                        ← Previous
                    </button>
                    <button
                        type="button"
                        disabled={nextNumber === null}
                        onClick={() => goTo(nextNumber)}
                        className="rounded-md px-3 py-2 text-sm text-[#c9c4b7] transition hover:bg-white/5 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
                    >
                        Next →
                    </button>
                </nav>
            </main>
        </div>
    );
}