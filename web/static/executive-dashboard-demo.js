const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const brandTrack = document.querySelector(".brand-track");
const brandSourceSet = brandTrack?.querySelector(".brand-set");
let brandResizeFrame = 0;

function rebuildBrandRail() {
  if (!brandTrack || !brandSourceSet) return;

  brandTrack.querySelectorAll("[data-brand-clone]").forEach((clone) => clone.remove());
  const brandSetWidth = brandSourceSet.getBoundingClientRect().width;
  if (!brandSetWidth) return;

  const requiredSets = Math.ceil(window.innerWidth / brandSetWidth) + 2;
  for (let index = 1; index < requiredSets; index += 1) {
    const clone = brandSourceSet.cloneNode(true);
    clone.dataset.brandClone = "";
    clone.setAttribute("aria-hidden", "true");
    clone.querySelectorAll("img").forEach((image) => image.setAttribute("alt", ""));
    brandTrack.append(clone);
  }

  brandTrack.style.setProperty("--brand-loop-width", `${brandSetWidth}px`);
  brandTrack.style.setProperty("--brand-duration", `${brandSetWidth / 34}s`);
}

rebuildBrandRail();

window.addEventListener("resize", () => {
  cancelAnimationFrame(brandResizeFrame);
  brandResizeFrame = requestAnimationFrame(rebuildBrandRail);
});

if (!reducedMotion.matches) {
  document.documentElement.classList.add("motion-enabled");

  panels.forEach((panel, index) => {
    panel.style.setProperty("--panel-delay", `${index * 85}ms`);
  });

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14 }
  );

  panels.forEach((panel) => observer.observe(panel));

  if (window.matchMedia("(pointer: fine)").matches) {
    document.addEventListener("pointermove", (event) => {
      const activePanel = event.target.closest?.(".panel") || null;

      panels.forEach((panel) => {
        const isActive = panel === activePanel;
        panel.classList.toggle("is-pointer-active", isActive);
        if (!isActive) return;

        const bounds = panel.getBoundingClientRect();
        panel.style.setProperty("--pointer-x", `${((event.clientX - bounds.left) / bounds.width) * 100}%`);
        panel.style.setProperty("--pointer-y", `${((event.clientY - bounds.top) / bounds.height) * 100}%`);
      });
    });
  }
} else {
  panels.forEach((panel) => panel.classList.add("is-visible"));
}
