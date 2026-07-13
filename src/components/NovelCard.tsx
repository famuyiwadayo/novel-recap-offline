// NovelCard.tsx
//
// One cover-art tile in the Library grid. Reads persisted data (title,
// cover, downloaded/total chapters) from the Novel record — that's what
// survives a restart — and overlays LIVE progress from the Zustand store
// only while a scrape for this novel is actually in flight, so a card
// shows real-time progress during a download without needing the whole
// grid to poll or refetch.

import { Link } from "@tanstack/react-router";
import type { Novel, TaskStats } from "@/types";

const STATE_LABEL: Record<Novel["scrapeState"], string> = {
    pending: "Queued",
    discovering: "Finding chapters…",
    downloading: "Downloading…",
    complete: "Complete",
    error: "Error",
};

function CoverArt({ novel }: { novel: Novel }) {
    const src = novel.coverImagePath ?? novel.coverImageUrl;
    if (src) {
        return (
            <img
                src={src}
                alt=""
                className="aspect-[2/3] w-full rounded-lg object-cover shadow-lg shadow-black/40 ring-1 ring-white/5"
                loading="lazy"
            />
        );
    }
    // placeholder: initials on a deterministic-but-varied tint, so an empty
    // library still reads as a shelf of distinct books rather than a wall
    // of identical gray boxes
    const label = novel.title ?? novel.sourceUrl;
    const hue = Math.abs(hashCode(label)) % 360;
    const initials = (novel.title ?? "?")
        .split(/\s+/)
        .slice(0, 2)
        .map((w) => w[0]?.toUpperCase())
        .join("");
    return (
        <div
            className="flex aspect-[2/3] w-full items-center justify-center rounded-lg text-2xl font-semibold text-white/90 shadow-lg shadow-black/40 ring-1 ring-white/5"
            style={{ background: `linear-gradient(160deg, hsl(${hue} 45% 28%), hsl(${hue} 55% 16%))` }}
        >
            {initials || "?"}
        </div>
    );
}

function hashCode(s: string): number {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i);
    return h;
}

export function NovelCard({ novel, liveStats }: { novel: Novel; liveStats?: TaskStats }) {
    const inProgress = novel.scrapeState === "discovering" || novel.scrapeState === "downloading";
    const total = liveStats?.total || novel.totalChapters;
    const done = inProgress && liveStats ? liveStats.success : novel.downloadedChapters;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;

    return (
        <Link
            to="/novel/$novelId"
            params={{ novelId: String(novel.id) }}
            className="group block focus:outline-none"
        >
            <div className="relative overflow-hidden rounded-lg transition-transform duration-200 group-hover:-translate-y-1 group-focus-visible:-translate-y-1 group-focus-visible:ring-2 group-focus-visible:ring-teal-400">
                <CoverArt novel={novel} />
                {inProgress && (
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-2 pb-2 pt-4">
                        <div className="h-1 w-full overflow-hidden rounded-full bg-white/20">
                            <div
                                className="h-full rounded-full bg-teal-400 transition-[width] duration-300"
                                style={{ width: `${pct}%` }}
                            />
                        </div>
                    </div>
                )}
                {novel.scrapeState === "error" && (
                    <div className="absolute right-1.5 top-1.5 rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                        Error
                    </div>
                )}
            </div>

            <div className="mt-2">
                <h3 className="truncate text-sm font-medium text-slate-100">
                    {novel.title ?? "Untitled"}
                </h3>
                <p className="truncate text-xs text-slate-500">
                    {novel.author.filter(Boolean).join(", ") || "Unknown author"}
                </p>
                {inProgress && (
                    <p className="mt-0.5 text-xs text-teal-400">
                        {STATE_LABEL[novel.scrapeState]} {total > 0 && `— ${done}/${total}`}
                    </p>
                )}
            </div>
        </Link>
    );
}