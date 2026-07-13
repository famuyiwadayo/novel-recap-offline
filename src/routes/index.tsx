// Library home — grid of novels, similar to Apple Books. useNovelsQuery()
// is the persisted source of truth; the Zustand store overlays live
// progress for anything currently downloading. Refetching on
// task-completion is now handled by task-store.ts's invalidation bridge
// (queryClient.invalidateQueries on terminal events) — no manual
// "terminalSignature" effect needed here anymore.



import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useStatsByGroup } from "@/stores";
import { NovelCard } from "@/components";
import { useNovelsQuery, useScrapeNovelMutation } from "@/queries";



export const Route = createFileRoute("/")({
    component: LibraryPage,
});

function NewScrapeBar() {
    const [url, setUrl] = useState("");
    const scrapeNovel = useScrapeNovelMutation();

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!url.trim()) return;
        scrapeNovel.mutate(url.trim(), { onSuccess: () => setUrl("") });
    }

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-start">
            <div className="flex-1">
                <input
                    type="url"
                    required
                    placeholder="Paste a novel URL to add it to your library…"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
                />
                {scrapeNovel.isError && (
                    <p className="mt-1 text-xs text-rose-400">
                        {scrapeNovel.error instanceof Error ? scrapeNovel.error.message : String(scrapeNovel.error)}
                    </p>
                )}
            </div>
            <button
                type="submit"
                disabled={scrapeNovel.isPending || !url.trim()}
                className="shrink-0 rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
            >
                {scrapeNovel.isPending ? "Adding…" : "Add to library"}
            </button>
        </form>
    );
}

function LibraryPage() {
    const { data: novels, isLoading } = useNovelsQuery();
    const statsByGroup = useStatsByGroup();

    return (
        <main className="mx-auto max-w-5xl px-6 py-6">
            <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <NewScrapeBar />
            </div>

            {isLoading ? (
                <p className="text-sm text-slate-500">Loading your library…</p>
            ) : !novels || novels.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 px-6 py-16 text-center">
                    <p className="text-sm text-slate-500">
                        Your library is empty — paste a novel URL above to get started.
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
                    {novels.map((novel) => (
                        <NovelCard key={novel.id} novel={novel} liveStats={statsByGroup.get(String(novel.id))} />
                    ))}
                </div>
            )}
        </main>
    );
}