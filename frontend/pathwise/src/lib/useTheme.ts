import { useEffect, useState } from "react";

/** Visual theme + density, persisted to localStorage and reflected on <html>
 *  as data-theme / data-density (read by styles/tokens.css). New in v2. */
export type ThemeName = "refined" | "warm" | "bold";
export type Density = "compact" | "comfortable" | "spacious";

const THEME_KEY = "pw-theme";
const DENSITY_KEY = "pw-density";

export function useTheme() {
  const [theme, setTheme] = useState<ThemeName>(
    () => (localStorage.getItem(THEME_KEY) as ThemeName) || "refined",
  );
  const [density, setDensity] = useState<Density>(
    () => (localStorage.getItem(DENSITY_KEY) as Density) || "comfortable",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    localStorage.setItem(DENSITY_KEY, density);
  }, [density]);

  return { theme, setTheme, density, setDensity };
}
