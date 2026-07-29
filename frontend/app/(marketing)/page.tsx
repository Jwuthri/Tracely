import Landing from "./Landing";

export const metadata = {
  title: "Tracely — trace-native CI/CD for AI agents",
  description:
    "Production traces become regression tests. Tracely grades every agent run, clusters failures into issues, freezes them as hermetic cases, and blocks the PR that reintroduces them.",
};

export default function Page() {
  return <Landing />;
}
