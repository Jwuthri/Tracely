import type { MetadataRoute } from "next";

import { SITE_URL } from "@/app/lib/site";

// Deliberately minimal. Keeping a page OUT of the index is the job of `robots: { index: false }`
// metadata (see the (app)/(auth)/share layouts) — NOT of a Disallow rule here: a disallowed URL is
// never fetched, so the noindex tag on it is never read, and Google will happily list the bare URL
// if anything links to it. Disallow is for crawl budget only, which is why just /api is listed.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
