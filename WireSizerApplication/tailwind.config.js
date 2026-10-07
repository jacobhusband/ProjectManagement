/** @type {import('tailwindcss').Config} */
// Tailwind 3.4 is the release the old cdn.tailwindcss.com script served. Compiling it at
// build time means Wire Sizer styles itself with no internet access and no third-party
// script running inside the app.
export default {
  content: ['./index.html', './*.{ts,tsx}', './components/**/*.{ts,tsx}', './utils/**/*.{ts,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
};
