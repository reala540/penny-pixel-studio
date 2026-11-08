// The public Penny & Pixel website (Cloudflare Pages). It is separate from the studio: the studio links to it,
// it never links back. Its status comes from the "website_built" audit entry the engine writes after each build.
import { useQuery } from "@tanstack/react-query";
import { must } from "./api";
import { supabase } from "./supabase";

export const SITE_URL = (import.meta.env.VITE_SITE_URL as string | undefined) || "https://pennyandpixel.pages.dev";

export interface WebsiteArticle { id: string; title: string; slug: string }
export interface WebsiteBuild { at: string; articles: number; leftOut: string[]; published: WebsiteArticle[] }
/** settings.website_hidden: articles the owner took off the website ({hidden: {project id: {title, at}}}). */
export interface WebsiteHidden { hidden?: Record<string, { title: string; at: string }> }

export function useWebsiteStatus() {
  return useQuery({
    queryKey: ["website-build"],
    refetchInterval: 300_000,
    queryFn: async (): Promise<WebsiteBuild | null> => {
      const rows = (await must(supabase.from("audit_logs").select("created_at, details").eq("action", "website_built")
        .order("created_at", { ascending: false }).limit(1))) as { created_at: string; details: { articles?: number; left_out?: string[]; published?: WebsiteArticle[] } }[];
      if (!rows.length) return null;
      const d = rows[0].details ?? {};
      return { at: rows[0].created_at, articles: d.articles ?? 0, leftOut: d.left_out ?? [], published: d.published ?? [] };
    },
  });
}
