(() => {
  const sidebar = document.querySelector('.api-sidebar');
  if (!sidebar) return;
  const links = [...sidebar.querySelectorAll('.nav-list a[href*="#"]')];

  const update = () => {
    for (const link of links) {
      if (link.getAttribute('aria-current') === 'location') {
        link.removeAttribute('aria-current');
      }
      const target = new URL(link.href);
      if (location.hash && target.pathname === location.pathname && target.hash === location.hash) {
        link.setAttribute('aria-current', 'location');
      }
    }
  };

  addEventListener('hashchange', update);
  update();
})();
