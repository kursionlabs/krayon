(() => {
  const root = document.documentElement;
  const button = document.querySelector('.theme-toggle');
  if (!button) return;

  const preference = matchMedia('(prefers-color-scheme: dark)');
  let saved;
  try { saved = localStorage.getItem('krayon-docs-theme'); } catch (error) { saved = null; }
  let followsSystem = saved !== 'light' && saved !== 'dark';

  const mode = () => root.dataset.theme === 'dark' ? 'dark' : 'light';
  const updateButton = () => {
    const next = mode() === 'dark' ? 'light' : 'dark';
    const label = `Switch to ${next} mode`;
    button.setAttribute('aria-label', label);
    button.title = label;
    button.querySelector('.theme-toggle-label').textContent = `${next[0].toUpperCase()}${next.slice(1)} mode`;
    button.querySelector('.theme-toggle-icon').textContent = next === 'dark' ? '☾' : '☀';
  };

  button.addEventListener('click', () => {
    root.dataset.theme = mode() === 'dark' ? 'light' : 'dark';
    followsSystem = false;
    try { localStorage.setItem('krayon-docs-theme', mode()); } catch (error) { /* Keep this page's choice. */ }
    updateButton();
  });
  preference.addEventListener('change', () => {
    if (!followsSystem) return;
    root.dataset.theme = preference.matches ? 'dark' : 'light';
    updateButton();
  });

  updateButton();
  button.hidden = false;
})();
