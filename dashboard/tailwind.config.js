/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: v("surface"),
        sunken: v("sunken"),
        ink: v("ink"),
        muted: v("muted"),
        line: v("line"),
        pixel: v("pixel"),
        "pixel-soft": v("pixel-soft"),
        cyan: v("cyan"),
        penny: v("penny"),
        "penny-soft": v("penny-soft"),
        gold: v("gold"),
        alert: v("alert"),
        "alert-soft": v("alert-soft"),
        ok: v("ok"),
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', "system-ui", "sans-serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.875rem", { lineHeight: "1.3rem" }],
        base: ["1rem", { lineHeight: "1.55rem" }],
        lg: ["1.2rem", { lineHeight: "1.7rem" }],
        xl: ["1.44rem", { lineHeight: "1.9rem" }],
        "2xl": ["1.728rem", { lineHeight: "2.1rem" }],
        "3xl": ["2.488rem", { lineHeight: "2.7rem" }],
      },
    },
  },
  plugins: [],
};
