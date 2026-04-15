/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,jsx,ts,tsx}",
    "./src/**/*.{js,jsx,ts,tsx}",
    "./components/**/*.{js,jsx,ts,tsx}",
  ],
  // presets removed — NativeWind no longer needed
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "rgb(var(--color-surface) / <alpha-value>)",
          raised: "rgb(var(--color-surface-raised) / <alpha-value>)",
          overlay: "rgb(var(--color-surface-overlay) / <alpha-value>)",
          border: "rgb(var(--color-surface-border) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          hover: "rgb(var(--color-accent-hover) / <alpha-value>)",
          muted: "rgb(var(--color-accent-muted) / <alpha-value>)",
        },
        text: {
          DEFAULT: "rgb(var(--color-text) / <alpha-value>)",
          muted: "rgb(var(--color-text-muted) / <alpha-value>)",
          dim: "rgb(var(--color-text-dim) / <alpha-value>)",
        },
        input: {
          DEFAULT: "rgb(var(--color-input-bg) / <alpha-value>)",
          border: "rgb(var(--color-input-border) / <alpha-value>)",
        },
        success: "rgb(var(--color-success) / <alpha-value>)",
        warning: {
          DEFAULT: "rgb(var(--color-warning) / <alpha-value>)",
          muted: "rgb(var(--color-warning-muted) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--color-danger) / <alpha-value>)",
          muted: "rgb(var(--color-danger-muted) / <alpha-value>)",
        },
        purple: "rgb(var(--color-purple) / <alpha-value>)",
        skeleton: "rgb(var(--color-skeleton) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
