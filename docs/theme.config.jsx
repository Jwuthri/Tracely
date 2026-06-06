const config = {
  logo: (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 700 }}>
      <span style={{ color: "#22d3ee" }}>◆</span> Tracely SDK
    </span>
  ),
  project: {
    link: "https://github.com/julien-heysam/Tracely",
  },
  docsRepositoryBase: "https://github.com/julien-heysam/Tracely/tree/master/docs",
  color: { hue: 190, saturation: 80 }, // cyan, to match the Tracely app accent
  footer: {
    content: (
      <span>
        Tracely — trace-native CI/CD for AI agents · the recorded run <em>is</em> the test.
      </span>
    ),
  },
  head: (
    <>
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta property="og:title" content="Tracely SDK" />
      <meta property="og:description" content="Instrument your AI agents and ship them to Tracely over OTLP." />
    </>
  ),
  sidebar: {
    defaultMenuCollapseLevel: 1,
    toggleButton: true,
  },
  toc: {
    backToTop: true,
  },
};

export default config;
