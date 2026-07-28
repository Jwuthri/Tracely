const REPO = "https://github.com/Jwuthri/Tracely";

// The app's sidebar mark (frontend/app/components/Sidebar.tsx), reused so docs and product share a face.
const Logo = () => (
  <span className="tracely-logo">
    <span className="mark">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M12 2 22 12 12 22 2 12Z" stroke="#22d3ee" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="2.7" fill="#22d3ee" />
      </svg>
    </span>
    <span>
      <span className="name">Tracely</span>
      <span className="kicker" style={{ display: "block" }}>
        sdk &amp; cli
      </span>
    </span>
  </span>
);

const config = {
  logo: <Logo />,
  logoLink: "/",
  project: { link: REPO },
  docsRepositoryBase: `${REPO}/tree/master/docs`,
  color: { hue: 187, saturation: 85, lightness: 53 }, // #22d3ee — the app's `signal`
  backgroundColor: { dark: "9,11,16" }, // ink #090b10
  // The product is dark-only; a light docs theme would be the odd one out.
  darkMode: false,
  nextThemes: { defaultTheme: "dark", forcedTheme: "dark" },
  navigation: { prev: true, next: true },
  footer: {
    content: (
      <span style={{ fontSize: 13 }}>
        Tracely — trace-native CI/CD for AI agents · the recorded run <em>is</em> the test.
      </span>
    ),
  },
  head: (
    <>
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta name="theme-color" content="#090b10" />
      <meta property="og:title" content="Tracely SDK" />
      <meta
        property="og:description"
        content="Instrument your AI agents and ship their traces to Tracely over OTLP."
      />
    </>
  ),
  sidebar: { defaultMenuCollapseLevel: 1, toggleButton: true },
  toc: { backToTop: true, title: "On this page" },
  editLink: { content: "Edit this page on GitHub" },
  feedback: { content: "Question? Give us feedback", labels: "documentation" },
};

export default config;
