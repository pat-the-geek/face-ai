/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Sans-serif système — cohérence Claude UI / OS native, lisibilité écran
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Text"',
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          "sans-serif",
        ],
        // Conservé pour les badges et footers (esthétique forensique-museum)
        mono: ['"Space Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        bg: {
          DEFAULT: "var(--bg-primary)",
          secondary: "var(--bg-secondary)",
        },
        ink: {
          DEFAULT: "var(--text-primary)",
          muted: "var(--text-secondary)",
        },
        accent: "var(--accent)",
        border: "var(--border)",
      },
    },
  },
  plugins: [],
};
