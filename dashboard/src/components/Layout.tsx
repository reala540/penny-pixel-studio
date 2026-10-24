import { Bot, CalendarDays, Clapperboard, Compass, Library, ListChecks, LogOut, Settings, CircleHelp } from "lucide-react";
import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSetting } from "../lib/api";
import { supabase } from "../lib/supabase";
import { Loading } from "./ui";

const NAV = [
  { to: "/", label: "Mission", icon: Bot, end: true },
  { to: "/week", label: "Rundown", icon: ListChecks },
  { to: "/review", label: "Review", icon: Clapperboard },
  { to: "/calendar", label: "Calendar", icon: CalendarDays },
  { to: "/research", label: "Research", icon: Compass },
  { to: "/library", label: "Library", icon: Library },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-ink" />
        <circle cx="12" cy="16" r="6" className="fill-gold" />
        <rect x="17" y="10" width="11" height="12" rx="2" className="fill-cyan" />
      </svg>
      <div className="leading-tight">
        <p className="font-display text-base font-bold">Penny &amp; Pixel</p>
        <p className="text-xs text-muted">Studio</p>
      </div>
    </div>
  );
}

export default function Layout() {
  const paused = useSetting<boolean>("paused", false).data;
  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="hidden border-r border-line bg-surface md:block">
      <aside className="sticky top-0 flex h-screen flex-col px-4 py-5">
        <Brand />
        <nav aria-label="Main" className="mt-8 flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>
              <Icon size={18} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex flex-col gap-1 border-t border-line pt-3">
          <NavLink to="/help" className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-sunken hover:text-ink">
            <CircleHelp size={18} aria-hidden /> Help
          </NavLink>
          <button onClick={() => supabase.auth.signOut()} className="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-sunken hover:text-ink">
            <LogOut size={18} aria-hidden /> Sign out
          </button>
        </div>
      </aside>
      </div>

      <div className="flex min-w-0 flex-col">
        <div className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden">
          <Brand />
          <NavLink to="/help" aria-label="Help" className="rounded-lg p-2 text-muted"><CircleHelp size={20} /></NavLink>
        </div>
        {paused && (
          <div role="status" className="bg-alert px-4 py-2 text-center text-sm font-medium text-white">
            Publishing is paused. Nothing will be posted until you resume it in Settings.
          </div>
        )}
        <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-28 pt-6 sm:px-6 md:pb-12">
          <Suspense fallback={<Loading label="Loading page" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex overflow-x-auto border-t border-line bg-surface md:hidden">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `flex min-w-[72px] flex-1 flex-col items-center gap-0.5 px-2 py-2 text-xs font-medium ${isActive ? "text-pixel" : "text-muted"}`}>
            <Icon size={20} aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
