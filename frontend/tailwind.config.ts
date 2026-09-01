import type { Config } from 'tailwindcss'

/**
 * HireHQ design tokens.
 *
 * A single accent hue (indigo) plus a warm-grey neutral ramp, so the interface reads as
 * one system rather than a collection of components. Semantic colours are defined once
 * here and referenced everywhere, which is what keeps status badges consistent across
 * the pipeline, the candidate detail page and the dashboard.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
        ink: {
          50: '#f8f8f7',
          100: '#f1f1ef',
          200: '#e5e5e1',
          300: '#d2d2cc',
          400: '#a3a39c',
          500: '#76766f',
          600: '#57574f',
          700: '#43433d',
          800: '#2a2a26',
          900: '#1a1a17',
          950: '#0e0e0c',
        },
        success: { 50: '#ecfdf5', 100: '#d1fae5', 500: '#10b981', 600: '#059669', 700: '#047857' },
        warning: { 50: '#fffbeb', 100: '#fef3c7', 500: '#f59e0b', 600: '#d97706', 700: '#b45309' },
        danger: { 50: '#fef2f2', 100: '#fee2e2', 500: '#ef4444', 600: '#dc2626', 700: '#b91c1c' },
        info: { 50: '#eff6ff', 100: '#dbeafe', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        // Slightly tightened tracking on display sizes; optical correction that keeps
        // large headings from looking loose.
        'display-lg': ['3.5rem', { lineHeight: '1.05', letterSpacing: '-0.03em' }],
        display: ['2.5rem', { lineHeight: '1.1', letterSpacing: '-0.025em' }],
        'title-lg': ['1.75rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        title: ['1.25rem', { lineHeight: '1.3', letterSpacing: '-0.015em' }],
      },
      borderRadius: { xl: '0.75rem', '2xl': '1rem', '3xl': '1.5rem' },
      boxShadow: {
        card: '0 1px 2px 0 rgb(16 16 14 / 0.04), 0 1px 3px 0 rgb(16 16 14 / 0.06)',
        'card-hover': '0 4px 12px -2px rgb(16 16 14 / 0.08), 0 2px 6px -2px rgb(16 16 14 / 0.06)',
        popover: '0 12px 32px -8px rgb(16 16 14 / 0.16), 0 4px 12px -4px rgb(16 16 14 / 0.08)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
      },
      animation: {
        'fade-in': 'fade-in 180ms ease-out',
        'slide-up': 'slide-up 220ms cubic-bezier(0.16, 1, 0.3, 1)',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
}

export default config
