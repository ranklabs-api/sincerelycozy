(() => {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');

  function rotate({ root, slideSelector, interval, labelsSelector, pauseOnRootHover, pauseOnFocus }) {
    if (!root) return;
    const slides = [...root.querySelectorAll(slideSelector)].filter((slide) => {
      const use = slide.dataset.use;
      return use === undefined || use !== '';
    });
    const labels = labelsSelector ? [...root.querySelectorAll(labelsSelector)] : [];
    if (!slides.length) return;

    let current = 0;
    let timer;
    let paused = false;

    function useOf(el) {
      return el && el.dataset ? el.dataset.use || '' : '';
    }

    function show(index) {
      current = (index + slides.length) % slides.length;
      const activeSlide = slides[current];
      slides.forEach((slide, i) => {
        const active = i === current;
        slide.classList.toggle('is-active', active);
        slide.setAttribute('aria-hidden', String(!active));
        slide.inert = !active;
      });
      const use = useOf(activeSlide);
      labels.forEach((label) => {
        const active = Boolean(use) && useOf(label) === use;
        label.classList.toggle('is-active', active);
        if (active) label.setAttribute('aria-current', 'true');
        else label.removeAttribute('aria-current');
      });
    }

    function schedule() {
      clearInterval(timer);
      if (!motion.matches && !paused && !document.hidden && slides.length > 1) {
        timer = setInterval(() => show(current + 1), interval);
      }
    }

    labels.forEach((label) => {
      label.addEventListener('click', () => {
        const use = useOf(label);
        const index = slides.findIndex((slide) => useOf(slide) === use);
        if (index >= 0) {
          show(index);
          schedule();
        }
      });
    });

    if (pauseOnRootHover) {
      root.addEventListener('mouseenter', () => { paused = true; schedule(); });
      root.addEventListener('mouseleave', () => { paused = false; schedule(); });
    }
    if (pauseOnFocus) {
      root.addEventListener('focusin', () => { paused = true; schedule(); });
      root.addEventListener('focusout', (event) => {
        if (!root.contains(event.relatedTarget)) {
          paused = false;
          schedule();
        }
      });
    }

    motion.addEventListener('change', schedule);
    document.addEventListener('visibilitychange', schedule);
    show(0);
    schedule();
  }

  rotate({
    root: document.querySelector('#banners'),
    slideSelector: '.carousel-slide',
    interval: 5500,
    pauseOnRootHover: true,
    pauseOnFocus: true
  });

  rotate({
    root: document.querySelector('#multifunction'),
    slideSelector: '.rotation-photo',
    labelsSelector: '.multifunction-list [data-use]',
    interval: 2500,
    pauseOnRootHover: false,
    pauseOnFocus: false
  });
})();
