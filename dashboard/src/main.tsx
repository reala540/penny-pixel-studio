import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AuthGate from "./components/AuthGate";
import Layout from "./components/Layout";
import { Loading, ToastProvider } from "./components/ui";
import "./index.css";
import { useUiMode } from "./lib/uiMode";
import { Privacy, Terms } from "./pages/Legal";

// Each page loads on first visit, so the sign-in screen stays light.
const Calendar = lazy(() => import("./pages/Calendar"));
const ControlRoom = lazy(() => import("./pages/ControlRoom"));
const ControlRoomDemo = lazy(() => import("./pages/ControlRoom").then((m) => ({ default: m.ControlRoomDemo })));
const Help = lazy(() => import("./pages/Help"));
const Home = lazy(() => import("./pages/Home"));
const LibraryPage = lazy(() => import("./pages/Library"));
const Research = lazy(() => import("./pages/Research"));
const Review = lazy(() => import("./pages/Review"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const Ideas = lazy(() => import("./pages/Ideas"));
const ApiManager = lazy(() => import("./pages/ApiManager"));
const Activity = lazy(() => import("./pages/Activity"));
const Setup = lazy(() => import("./pages/Setup"));

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 20_000, refetchOnWindowFocus: true, retry: 1 } } });

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

/** Simple menu starts on This Week; Advanced on Mission Control. */
function Start() {
  const { mode, loading } = useUiMode();
  if (loading) return <Loading label="Loading" />;
  return mode === "simple" ? <Navigate to="/week" replace /> : <ControlRoom />;
}

function Studio() {
  return (
          <AuthGate>
            <Suspense fallback={<div className="mx-auto max-w-6xl px-4 pt-6"><Loading label="Loading page" /></div>}>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Start />} />
                <Route path="mission" element={<ControlRoom />} />
                <Route path="activity" element={<Activity />} />
                <Route path="setup" element={<Setup />} />
                <Route path="week" element={<Home />} />
                <Route path="review" element={<Review />} />
                <Route path="review/:projectId" element={<Review />} />
                <Route path="calendar" element={<Calendar />} />
                <Route path="research" element={<Research />} />
                <Route path="library" element={<LibraryPage />} />
                <Route path="ideas" element={<Ideas />} />
                <Route path="api" element={<ApiManager />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="help" element={<Help />} />
                <Route path="*" element={<Start />} />
              </Route>
            </Routes>
            </Suspense>
          </AuthGate>
  );
}
