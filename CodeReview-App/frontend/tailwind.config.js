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
    },
  },
  plugins: [],
};
