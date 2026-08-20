import "@testing-library/jest-dom/vitest";

// jsdom ships no matchMedia, and every component that respects prefers-reduced-motion asks for
// it on mount. Answer "no preference" — the same thing a browser says by default.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
