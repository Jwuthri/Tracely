import type { Metadata } from "next";

import { DOCS_URL, GITHUB_URL, SITE_DESCRIPTION, SITE_TITLE, SITE_URL } from "@/app/lib/site";
import Landing from "./Landing";

export const metadata: Metadata = {
  // `absolute` opts out of the root layout's "%s — Tracely" template, which would otherwise render
  // "Tracely — … — Tracely". Google truncates around 60 chars; the brand is already at the front.
  title: { absolute: SITE_TITLE },
  description: SITE_DESCRIPTION,
  // Only the homepage declares a canonical, and only for itself: a site-wide canonical on the root
  // layout would point every future page at "/" and collapse them all into one result.
  alternates: { canonical: "/" },
};

// Structured data. `SoftwareApplication` is what makes Google render the pricing/category chips,
// and `Organization` is what ties the brand name to the GitHub and docs profiles. Plain script tag
// — Next has no JSON-LD helper and none is needed.
const JSON_LD = [
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "Tracely",
    applicationCategory: "DeveloperApplication",
    operatingSystem: "Web, Linux, macOS",
    url: SITE_URL,
    description: SITE_DESCRIPTION,
    license: "https://opensource.org/licenses/MIT",
    softwareHelp: DOCS_URL,
    codeRepository: GITHUB_URL,
    offers: [
      { "@type": "Offer", name: "Self-host", price: "0", priceCurrency: "USD" },
      { "@type": "Offer", name: "Free", price: "0", priceCurrency: "USD" },
      { "@type": "Offer", name: "Team", price: "49", priceCurrency: "USD" },
    ],
  },
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Tracely",
    url: SITE_URL,
    sameAs: [GITHUB_URL],
  },
];

export default function Page() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />
      <Landing />
    </>
  );
}
