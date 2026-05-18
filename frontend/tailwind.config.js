/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"PP Editorial New"', 'Fraunces', 'ui-serif', 'Georgia', 'serif'],
        sans: ['"Roboto Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
        mono: ['"Roboto Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        // Warm gold / copper palette - matches reference (Tata "get a quote" copper)
        gold: {
          50:  '#fbf5ec',
          100: '#f5e8d1',
          200: '#ecd2a7',
          300: '#e0b87a',
          400: '#d4a574',
          500: '#c8914f',
          600: '#b8864f',
          700: '#9a6f3e',
          800: '#7a5830',
          900: '#5c4125',
        },
        // Near-black zinc surfaces
        ink: {
          950: '#0a0a0a',
          900: '#101010',
          850: '#141416',
          800: '#1a1a1d',
          750: '#202024',
          700: '#26262b',
        },
      },
      borderRadius: {
        '2.5xl': '1.25rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        'diffuse': '0 20px 40px -15px rgba(0,0,0,0.3)',
        'gold-glow': '0 0 0 1px rgba(212,165,116,0.2), 0 8px 32px rgba(212,165,116,0.12)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        wave1: {
          '0%, 100%': { transform: 'scaleY(0.4)' },
          '50%': { transform: 'scaleY(1)' },
        },
        wave2: {
          '0%, 100%': { transform: 'scaleY(1)' },
          '50%': { transform: 'scaleY(0.3)' },
        },
        wave3: {
          '0%, 100%': { transform: 'scaleY(0.6)' },
          '50%': { transform: 'scaleY(1)' },
        },
      },
      animation: {
        shimmer: 'shimmer 2s linear infinite',
        float: 'float 3s ease-in-out infinite',
        'fade-up': 'fade-up 0.4s cubic-bezier(0.22, 1, 0.36, 1)',
        wave1: 'wave1 0.6s ease-in-out infinite',
        wave2: 'wave2 0.8s ease-in-out infinite 0.15s',
        wave3: 'wave3 0.5s ease-in-out infinite 0.3s',
      },
      typography: {
        DEFAULT: {
          css: {
            color: 'var(--text)',
            a: {
              color: 'var(--accent)',
              '&:hover': { color: 'var(--accent-strong)' },
            },
            'h1, h2, h3, h4': {
              color: 'var(--text)',
              fontFamily: '"PP Editorial New", Fraunces, ui-serif, Georgia, serif',
              letterSpacing: '-0.02em',
            },
            strong: { color: 'var(--text)' },
            code: {
              color: 'var(--accent)',
              fontFamily: '"Roboto Mono", ui-monospace, monospace',
            },
            pre: {
              backgroundColor: 'var(--bg-sunken)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
            },
            blockquote: {
              borderLeftColor: 'var(--accent)',
              color: 'var(--text-muted)',
            },
          },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
