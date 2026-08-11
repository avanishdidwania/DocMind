/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#111319',
        surface: {
          DEFAULT: '#111319',
          bright: '#373940',
          container: '#1e1f26',
          'container-high': '#282a30',
          'container-highest': '#33343b',
          'container-low': '#191b22',
          'container-lowest': '#0c0e14',
          dim: '#111319',
          variant: '#33343b',
        },
        primary: {
          DEFAULT: '#8b5cf6',
          container: '#a078ff',
          dim: '#d0bcff',
        },
        secondary: {
          DEFAULT: '#3b82f6',
          container: '#0566d9',
          dim: '#adc6ff',
        },
        tertiary: {
          DEFAULT: '#06b6d4',
          container: '#009eb9',
          dim: '#4cd7f6',
        },
        'on-surface': '#e2e2eb',
        'on-surface-variant': '#cbc3d7',
        outline: '#958ea0',
        'outline-variant': '#494454',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        display: ['Outfit', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        'glow-primary': '0 0 20px rgba(139, 92, 246, 0.15)',
        'glow-secondary': '0 0 20px rgba(59, 130, 246, 0.15)',
        'glow-accent': '0 0 25px rgba(6, 182, 212, 0.2)',
      }
    },
  },
  plugins: [],
}
