import type { Config } from "tailwindcss";

// Dark theme. The pages were written with Tailwind's light "slate" palette, so the palette is
// remapped here (slate-900 is now the light text colour, slate-100 a raised dark surface)
// instead of touching every class. Tints used for status banners are darkened the same way.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#1a1b23", // page background
        surface: "#23252f", // cards, inputs, tables
        chrome: "#14161d", // top bar
        rail: "#0d1016", // sidebar
        accent: { DEFAULT: "#ff7a59", hover: "#ff6a45", fg: "#1a0f0b" },
        slate: {
          50: "#2a2d39",
          100: "#2b2e3a",
          200: "#323644",
          300: "#434859",
          400: "#868fa0", // muted text: at least 4.5:1 on the dark surfaces
          500: "#98a1b0",
          600: "#a5adbb",
          700: "#c3c9d4",
          800: "#dde1e8",
          900: "#eef1f6",
        },
        red: { 50: "#3b1f23", 100: "#4a2328", 700: "#ff8a80", 800: "#fca5a5" },
        green: { 50: "#14301f", 100: "#17391f", 700: "#4ade80", 800: "#86efac" },
        amber: {
          50: "#33270f",
          100: "#3d2e10",
          200: "#5c4515",
          400: "#fbbf24",
          600: "#f5a524",
          700: "#fbbf24",
          800: "#fcd34d",
          900: "#fde68a",
        },
        blue: { 50: "#14233b", 100: "#172a46", 800: "#93c5fd" },
        violet: { 100: "#2b2250", 800: "#c4b5fd" },
      },
    },
  },
  plugins: [],
};

export default config;
