(() => {
  "use strict";

  const CANVAS_WIDTH = 1600;
  const CANVAS_HEIGHT = 900;
  const COMPACT_QUERY = window.matchMedia("(max-width: 1000px)");
  const diagram = document.querySelector(".architecture-diagram");
  const canvas = document.querySelector(".diagram-canvas");
  const footer = document.querySelector(".architecture-footer");

  if (!diagram || !canvas) return;

  const fitDiagram = () => {
    if (COMPACT_QUERY.matches) {
      diagram.style.removeProperty("height");
      canvas.style.removeProperty("transform");
      canvas.style.removeProperty("margin-left");
      return;
    }

    const diagramTop = diagram.getBoundingClientRect().top;
    const footerHeight = footer ? footer.getBoundingClientRect().height : 0;
    const availableWidth = diagram.clientWidth;
    const availableHeight = Math.max(1, window.innerHeight - diagramTop - footerHeight - 14);
    const scale = Math.min(1, availableWidth / CANVAS_WIDTH, availableHeight / CANVAS_HEIGHT);

    canvas.style.transform = `scale(${scale})`;
    canvas.style.marginLeft = `${Math.max(0, (availableWidth - CANVAS_WIDTH * scale) / 2)}px`;
    diagram.style.height = `${Math.ceil(CANVAS_HEIGHT * scale)}px`;
  };

  const observer = new ResizeObserver(fitDiagram);
  observer.observe(diagram);
  window.addEventListener("resize", fitDiagram, { passive: true });
  COMPACT_QUERY.addEventListener("change", fitDiagram);
  fitDiagram();
})();
