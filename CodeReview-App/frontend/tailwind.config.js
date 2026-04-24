/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'ui-orange': '#fa4616',
        'ui-orange-dark': '#e03a0f',
        'ui-orange-light': '#fff1ed',
        'ui-navy': '#0d1b2a',
        'ui-navy-light': '#1b2d45',
        'ui-navy-lighter': '#253b56',
        'ui-g50': '#f8f9fa',
        'ui-g100': '#f1f3f5',
        'ui-g200': '#e9ecef',
        'ui-g300': '#dee2e6',
        'ui-g400': '#adb5bd',
        'ui-g500': '#6c757d',
        'ui-g600': '#495057',
        'ui-g700': '#343a40',
        'ui-g800': '#212529',
      },
      fontFamily: {
        sans: ['"Noto Sans"', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      backgroundImage: {
        'hero-gradient': 'linear-gradient(135deg, #0d1b2a 0%, #1b2d45 40%, #253b56 100%)',
        'orange-gradient': 'linear-gradient(135deg, #fa4616 0%, #ff6b3d 100%)',
        'mesh-bg': 'radial-gradient(at 20% 80%, rgba(250,70,22,0.06) 0%, transparent 50%), radial-gradient(at 80% 20%, rgba(13,27,42,0.04) 0%, transparent 50%)',
      },
      boxShadow: {
        'card': '0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)',
        'card-hover': '0 4px 16px rgba(0,0,0,0.08), 0 8px 32px rgba(0,0,0,0.04)',
        'glow-orange': '0 0 20px rgba(250,70,22,0.15), 0 0 40px rgba(250,70,22,0.05)',
        'elevated': '0 8px 30px rgba(0,0,0,0.08)',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'fade-in-up': 'fadeInUp 0.5s ease-out',
        'fade-in-down': 'fadeInDown 0.4s ease-out',
        'scale-in': 'scaleIn 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.4s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeInDown: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
};
