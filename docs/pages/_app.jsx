// Nextra bundles its own stylesheet; ours loads after it so the app-token overrides win.
import "../styles/globals.css";

export default function App({ Component, pageProps }) {
  return <Component {...pageProps} />;
}
