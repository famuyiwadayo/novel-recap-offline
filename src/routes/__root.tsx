// routes/__root.tsx
//
// Shared layout for every route: top nav (Library / Downloads) + the
// offline banner, both driven by the Zustand store so they stay in sync
// regardless of which page is active.

import { createRootRoute, Link, Outlet } from "@tanstack/react-router";
import { useOnline } from "@/stores";
// import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'

function ConnectivityBanner() {
    const online = useOnline();
    if (online) return null;
    return (
        <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 border-b border-amber-500/20 bg-amber-500/10 px-4 py-2 text-sm text-amber-300"
        >
            <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60 motion-reduce:animate-none" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
            </span>
            Offline — active work is paused and will resume automatically once connectivity returns.
        </div>
    );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
    return (
        <Link
            to={to}
            activeOptions={{ exact: to === "/" }}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-400 transition hover:text-slate-100 [&.active]:bg-slate-800 [&.active]:text-slate-100"
        >
            {children}
        </Link>
    );
}

export const Route = createRootRoute({
    component: () => (
        <div className="min-h-screen bg-slate-950 text-slate-100">
            <ConnectivityBanner />
            <header className="border-b border-slate-800 px-6 py-3">
                <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
                    <h1 className="text-sm font-semibold tracking-tight text-slate-300">Library</h1>
                    <nav className="flex items-center gap-1">
                        <NavLink to="/">Library</NavLink>
                        <NavLink to="/downloads">Downloads</NavLink>
                    </nav>
                </div>
            </header>
            <Outlet />
            {/* <TanStackRouterDevtools /> */}
        </div>
    ),
});