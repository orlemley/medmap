import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Light/dark theme for the whole site.
//
// The choice is saved per browser. Until someone picks one, the site follows
// the device's setting (and changes with it). index.html sets the same
// data-theme attribute before React loads, so pages don't flash white first.

const STORAGE_KEY = "medmap-theme";
const ThemeContext = createContext({ theme: "light", toggleTheme: () => {} });

const systemQuery = () => window.matchMedia("(prefers-color-scheme: dark)");

function readStored() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage can be blocked (private windows, strict settings)
  }
}

export function ThemeProvider({ children }) {
  const [stored, setStored] = useState(readStored);
  const [system, setSystem] = useState(() => (systemQuery().matches ? "dark" : "light"));
  const theme = stored ?? system;

  // Follow the device setting while the user hasn't chosen.
  useEffect(() => {
    const query = systemQuery();
    const onChange = () => setSystem(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggleTheme = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    setStored(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // the toggle still works for this visit
    }
  }, [theme]);

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
