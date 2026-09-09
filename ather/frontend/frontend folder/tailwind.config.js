/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        windy: {
          bg: '#14181d',
          surface: '#1c2128',
          card: 'rgba(23, 28, 35, 0.85)',
          panel: 'rgba(18, 22, 28, 0.92)',
          border: 'rgba(255, 255, 255, 0.08)',
          hover: 'rgba(255, 255, 255, 0.12)',
          red: '#e73827',
          blue: '#0099ff',
          cyan: '#00e5ff',
          accent: '#ff9800',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
}
