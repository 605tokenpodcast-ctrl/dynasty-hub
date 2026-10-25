// Tailwind settings for styles.css (same theme the page used with the Tailwind CDN).
module.exports = {
  content: ['./index.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        darkbg: '#0f172a',
        cardbg: '#1e293b',
        accent: '#3b82f6'
      }
    }
  }
};
