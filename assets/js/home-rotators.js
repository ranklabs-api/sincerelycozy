(() => {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  function rotate(root, slideSelector, onShow) {
    const slides = [...root.querySelectorAll(slideSelector)];
    const dots = [...root.querySelectorAll('.carousel-dots button')];
    let current = 0;
    let timer;
    let hovered = false;
    let interacted = false;
    function show(index) {
      current = index;
      slides.forEach((slide, i) => {
        const active = i === current;
        slide.classList.toggle('is-active', active);
        slide.setAttribute('aria-hidden', String(!active));
        slide.inert = !active;
      });
      dots.forEach((dot, i) => {
        if (i === current) dot.setAttribute('aria-current', 'true');
        else dot.removeAttribute('aria-current');
      });
      if (onShow) onShow(slides[current]);
    }
    function schedule() {
      clearInterval(timer);
      if (!motion.matches && !hovered && !interacted && !document.hidden) {
        timer = setInterval(() => show((current + 1) % slides.length), 5000);
      }
    }
    dots.forEach((dot, i) => dot.addEventListener('click', () => {
      interacted = true;
      schedule();
      show(i);
    }));
    root.addEventListener('mouseenter', () => { hovered = true; schedule(); });
    root.addEventListener('mouseleave', () => { hovered = false; schedule(); });
    // Keep focused content stable after keyboard interaction.
    root.addEventListener('focusin', () => { interacted = true; schedule(); });
    motion.addEventListener('change', schedule);
    document.addEventListener('visibilitychange', schedule);
    const controls = root.querySelector('.carousel-controls');
    if (controls) controls.hidden = false;
    show(0);
    schedule();
  }
  rotate(document.querySelector('#banners'), '.carousel-slide');
  const multifunction = document.querySelector('#multifunction');
  rotate(multifunction, '.rotation-photo', photo => {
    multifunction.querySelectorAll('.multifunction-list li').forEach(item => {
      item.classList.toggle('is-active', item.dataset.use === photo.dataset.use);
    });
  });
})();
