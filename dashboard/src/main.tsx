import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import AuthGate from "./components/AuthGate";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/ui";
import "./index.css";
import Calendar from "./pages/Calendar";
import Help from "./pages/Help";
import Home from "./pages/Home";
import { Privacy, Terms } from "./pages/Legal";
import LibraryPage from "./pages/Library";
import Research from "./pages/Research";
import Review from "./pages/Review";
import SettingsPage from "./pages/Settings";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 20_000, refetchOnWindowFocus: true, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="privacy" element={<Privacy />} />
            <Route path="terms" element={<Terms />} />
            <Route path="*" element={<Studio />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);

function Studio() {
  return (
          <AuthGate>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Home />} />
                <Route path="review" element={<Review />} />
                <Route path="review/:projectId" element={<Review />} />
                <Route path="calendar" element={<Calendar />} />
                <Route path="research" element={<Research />} />
                <Route path="library" element={<LibraryPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="help" element={<Help />} />
                <Route path="*" element={<Home />} />
              </Route>
            </Routes>
          </AuthGate>
  );
}
