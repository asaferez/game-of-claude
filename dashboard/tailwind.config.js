/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          DEFAULT: "#D4632A",
          light: "#E8834A",
          dark: "#A84E20",
        },
        surface: "#1C1917",
        card: "#292524",
        border: "#44403C",
        muted: "#78716C",
        gold: "#F59E0B",
      },
      keyframes: {
        "ring-fill": {
          "0%": { "stroke-dashoffset": "var(--circumference)" },
          "100%": { "stroke-dashoffset": "var(--offset)" },
        },
      },
      animation: {
        "ring-fill": "ring-fill 1s ease-out forwards",
      },
    },
  },
  plugins: [],
};
