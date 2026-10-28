import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import AuthGate from "./components/AuthGate";
import Layout from "./components/Layout";
import { Loading, reportError, ToastProvider } from "./components/ui";
import { announceChange } from "./lib/state";
import "./index.css";
import { legacyRedirect } from "./lib/routes";
import { Privacy, Terms } from "./pages/Legal";

// Each page loads on first visit, so the sign-in screen stays light.
const Activity = lazy(() => import("./pages/Activity"));
const Calendar = lazy(() => import("./pages/Calendar"));
const Content = lazy(() => import("./pages/Content"));
const ProjectPage = lazy(() => import("./pages/Content").then((m) => ({ default: m.ProjectPage })));
const ControlRoomDemo = lazy(() => import("./pages/ControlRoom").then((m) => ({ default: m.ControlRoomDemo })));
const Create = lazy(() => import("./pages/Create"));
const Help = lazy(() => import("./pages/Help"));
const Home = lazy(() => import("./pages/Home"));
const Ideas = lazy(() => import("./pages/Ideas"));
const Performance = lazy(() => import("./pages/Performance"));
const SettingsPage = lazy(() => import("./pages/Settings"));

// Every action that fails says so, even where a page didn't add its own message; every change tells the other tabs.
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 20_000, refetchOnWindowFocus: true, refetchOnReconnect: true, retry: 1 } },
  mutationCache: new MutationCache({
    onError: (error, _v, _c, mutation) => { if (!mutation.options.onError) reportError(error); },
    onSuccess: () => { void queryClient.invalidateQueries(); announceChange(); },
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="demo" element={<Suspense fallback={<Loading label="Loading demo" />}><ControlRoomDemo /></Suspense>} />
            <Route path="privacy" element={<Privacy />} />
            <Route path="terms" element={<Terms />} />
            <Route path="*" element={<Studio />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);

/** Old addresses (Telegram links, bookmarks, platform sign-in returns) go to their new page, keeping ?query and #anchor. */
function LegacyRedirect() {
  const { pathname, search, hash } = useLocation();
  return <Navigate to={legacyRedirect(pathname, search, hash) ?? "/"} replace />;
}

function Studio() {
  return (
    <AuthGate>
      <Suspense fallback={<div className="mx-auto max-w-6xl px-4 pt-6"><Loading label="Loading page" /></div>}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="create" element={<Create />} />
            <Route path="content" element={<Content />} />
            <Route path="content/ideas" element={<Ideas />} />
            <Route path="content/:projectId" element={<ProjectPage />} />
            <Route path="calendar" element={<Calendar />} />
            <Route path="activity" element={<Activity />} />
            <Route path="performance" element={<Performance />} />
            <Route path="settings/:section" element={<SettingsPage />} />
            <Route path="help" element={<Help />} />
            {["week", "mission", "review", "review/:id", "library", "ideas", "research", "setup", "api", "settings"].map((p) => (
              <Route key={p} path={p} element={<LegacyRedirect />} />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </AuthGate>
  );
}
