import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
      },
      colors: {
        ink: {
          DEFAULT: "#090b10",
          900: "#0b0e14",
          800: "#0f131b",
          700: "#141925",
          600: "#1a2030",
        },
        line: { DEFAULT: "#1b2230", soft: "#141a26", bright: "#28324a" },
        fg: { DEFAULT: "#e8ebf2", muted: "#9aa3b6", faint: "#5c6679" },
        signal: { DEFAULT: "#22d3ee", soft: "#7df0ff", dim: "#0e7490", deep: "#0a3a45" },
        ok: { DEFAULT: "#34d399", dim: "#0f3d33" },
        fail: { DEFAULT: "#fb7185", dim: "#451f2b" },
        warn: { DEFAULT: "#fbbf24", dim: "#3d2f12" },
        info: { DEFAULT: "#60a5fa", dim: "#16294a" },
        // span type accents
        t_agent: "#7aa2ff",
        t_llm: "#34d399",
        t_tool: "#fb923c",
        t_retriever: "#c084fc",
        t_step: "#8b94a7",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(34,211,238,0.25), 0 8px 30px -8px rgba(34,211,238,0.35)",
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 20px 40px -24px rgba(0,0,0,0.8)",
      },
      keyframes: {
        fadeup: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        grow: {
          "0%": { transform: "scaleX(0)" },
          "100%": { transform: "scaleX(1)" },
        },
        pulse2: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        fadeup: "fadeup 0.4s cubic-bezier(0.2,0.7,0.2,1) both",
        grow: "grow 0.5s cubic-bezier(0.2,0.7,0.2,1) both",
        pulse2: "pulse2 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
