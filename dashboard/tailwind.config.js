/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#6d28d9",
          light: "#8b5cf6",
          dark: "#4c1d95",
        },
        surface: "#0f0f1a",
        card: "#1a1a2e",
        border: "#2a2a3e",
        muted: "#6b7280",
        gold: "#f59e0b",
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
