import type { MetadataRoute } from "next";

import { SITE_URL } from "@/app/lib/site";

// Public, indexable routes only — the dashboard, auth pages and /share links are noindex (set on
// their layouts) and have no business here. Add every new marketing page to this list; a page
// missing from the sitemap is a page Google discovers late or not at all.
const ROUTES = [""];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return ROUTES.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified,
    changeFrequency: "weekly" as const,
    priority: path === "" ? 1 : 0.8,
  }));
}
