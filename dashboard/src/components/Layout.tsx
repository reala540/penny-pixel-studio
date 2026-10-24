import { Activity, Bot, CalendarDays, Clapperboard, Compass, KeyRound, Library, Lightbulb, ListChecks, LogOut, Settings, CircleHelp, Wrench } from "lucide-react";
import { ChevronDown } from "lucide-react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSetting } from "../lib/api";
import { supabase } from "../lib/supabase";
import { SIMPLE_PATHS, useUiMode } from "../lib/uiMode";
import { AutoPostBadge } from "./AutoPostToggle";
import ModeSwitch from "./ModeSwitch";
import RunningNow from "./RunningNow";
import ThemeControl from "./ThemeControl";
import Tour from "./Tour";
import { Loading } from "./ui";

const ALL_NAV = [
  { to: "/", label: "Mission Control", short: "Mission", icon: Bot, end: true },
  { to: "/week", label: "This Week", short: "Week", icon: ListChecks },
  { to: "/activity", label: "Activity", short: "Activity", icon: Activity },
  { to: "/review", label: "Review", short: "Review", icon: Clapperboard },
  { to: "/calendar", label: "Calendar", short: "Calendar", icon: CalendarDays },
  { to: "/ideas", label: "Ideas", short: "Ideas", icon: Lightbulb },
  { to: "/research", label: "Research", short: "Research", icon: Compass },
  { to: "/library", label: "Library", short: "Library", icon: Library },
  { to: "/api", label: "AI APIs", short: "AI APIs", icon: KeyRound },
  { to: "/setup", label: "Setup", short: "Setup", icon: Wrench },
  { to: "/settings", label: "Settings", short: "Settings", icon: Settings },
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
  const { mode } = useUiMode();
  const NAV = mode === "simple" ? ALL_NAV.filter((n) => SIMPLE_PATHS.has(n.to)) : ALL_NAV;
  const scroller = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const el = scroller.current;
    setMore(Boolean(el && el.scrollHeight - el.scrollTop - el.clientHeight > 4));
  }, []);
  useEffect(() => {
    measure();
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    Array.from(el.children).forEach((c) => ro.observe(c));
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [measure, mode]);
  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="hidden border-r border-line bg-surface md:block">
      <aside aria-label="Sidebar" className="sticky top-0 flex h-screen flex-col">
        {/* Scrolls on short screens or when zoomed in; the arrow at the bottom shows there's more below. */}
        <div ref={scroller} onScroll={measure} className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
          <Brand />
          <nav aria-label="Main" className="mt-5 flex flex-col gap-0.5">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}
                className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-1.5 text-sm font-medium [@media(min-height:900px)]:py-2 ${isActive ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>
                <Icon size={18} aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="min-h-4 flex-1" aria-hidden />
          <div className="flex flex-col gap-1 border-t border-line pt-3">
            <RunningNow />
            <AutoPostBadge />
            <div className="px-1 pt-1"><ModeSwitch compact /></div>
            <div className="flex items-center justify-between gap-2 px-1 pt-1">
              <ThemeControl compact />
              <NavLink to="/help" className="flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-sunken hover:text-ink">
                <CircleHelp size={17} aria-hidden /> Help
              </NavLink>
            </div>
            <button onClick={() => supabase.auth.signOut()} className="flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-left text-sm text-muted hover:bg-sunken hover:text-ink">
              <LogOut size={17} aria-hidden /> Sign out
            </button>
          </div>
        </div>
        {more && (
          <button type="button" onClick={() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" })}
            className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 bg-gradient-to-t from-surface via-surface/95 to-transparent pb-2 pt-6 text-xs font-medium text-muted hover:text-ink"
            aria-label="Scroll the menu down to see more">
            More <ChevronDown size={14} aria-hidden />
          </button>
        )}
      </aside>
      </div>

      <div className="flex min-w-0 flex-col">
        <div className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden">
          <Brand />
          <div className="flex items-center gap-1">
            <ThemeControl compact />
            <NavLink to="/help" aria-label="Help" className="rounded-lg p-2 text-muted"><CircleHelp size={20} /></NavLink>
            <button onClick={() => supabase.auth.signOut()} aria-label="Sign out" className="rounded-lg p-2 text-muted"><LogOut size={20} /></button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 border-b border-line bg-surface px-4 py-2 md:hidden"><RunningNow /><AutoPostBadge /></div>
        {paused && (
          <div role="status" className="bg-alert px-4 py-2 text-center text-sm font-medium text-surface">
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
        {NAV.map(({ to, short, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `flex min-w-[72px] flex-1 flex-col items-center gap-0.5 px-2 py-2 text-xs font-medium ${isActive ? "text-pixel" : "text-muted"}`}>
            <Icon size={20} aria-hidden />
            {short}
          </NavLink>
        ))}
      </nav>
      <Tour />
    </div>
  );
}
