import { ThemeProvider as NextThemesProvider } from "next-themes";
import { DEFAULT_THEME_PREFERENCE, THEME_STORAGE_KEY } from "@/lib/theme";

/** next-themes owns persistence + OS change listening; index.html owns pre-paint. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      storageKey={THEME_STORAGE_KEY}
      defaultTheme={DEFAULT_THEME_PREFERENCE}
      themes={["light", "dark"]}
      enableSystem
      enableColorScheme
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
