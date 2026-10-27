import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { normalizeStoredPreference } from "./lib/theme";

// Must run before ThemeProvider mounts (index.html does the same pre-paint).
try { normalizeStoredPreference(window.localStorage); } catch { /* storage unavailable */ }

createRoot(document.getElementById("root")!).render(<App />);
