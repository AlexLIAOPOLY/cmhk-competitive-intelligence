const demoData = {
  "2024": {
    siteTotal: "3,100", siteGrowth: "+5.6%",
    cmhk5g: "1,280", hkt5g: "1,510", three5g: "1,120", smt5g: "1,030",
    cmhkCompute: "1,120",
    mobileUsers: "309.6", mobileArpu: "129.8",
    homeUsers: "71.2", homeArpu: "181.6",
    contractValue: "14.2", businessUsers: "31.5",
    stores: "121", appMau: "176",
    cmhkRevenue: "84.1", hktRevenue: "77.8", threeRevenue: "52.1", smtRevenue: "49.3",
    ebitda: "29.4", ebitdaMargin: "34.9", netProfit: "9.8"
  },
  "2025": {
    siteTotal: "3,400", siteGrowth: "+7.1%",
    cmhk5g: "1,460", hkt5g: "1,670", three5g: "1,260", smt5g: "1,140",
    cmhkCompute: "1,420",
    mobileUsers: "328.4", mobileArpu: "134.2",
    homeUsers: "79.8", homeArpu: "190.4",
    contractValue: "16.5", businessUsers: "35.1",
    stores: "130", appMau: "198",
    cmhkRevenue: "90.2", hktRevenue: "80.6", threeRevenue: "54.8", smtRevenue: "50.7",
    ebitda: "31.9", ebitdaMargin: "35.3", netProfit: "11.1"
  },
  "2026": {
    siteTotal: "3,700", siteGrowth: "+8.4%",
    cmhk5g: "1,620", hkt5g: "1,810", three5g: "1,390", smt5g: "1,260",
    cmhkCompute: "1,680",
    mobileUsers: "342.8", mobileArpu: "138.6",
    homeUsers: "86.4", homeArpu: "198.2",
    contractValue: "18.6", businessUsers: "38.2",
    stores: "138", appMau: "218",
    cmhkRevenue: "96.8", hktRevenue: "84.2", threeRevenue: "57.4", smtRevenue: "52.6",
    ebitda: "34.8", ebitdaMargin: "35.9", netProfit: "12.4"
  }
};

const numberNodes = [...document.querySelectorAll("[data-key]")];
const periodButtons = [...document.querySelectorAll("[data-period]")];
const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const numberAnimations = new WeakMap();

function formatAnimatedValue(template, value) {
  const match = template.match(/^([^\d-]*)(-?[\d,]+(?:\.\d+)?)(.*)$/);
  if (!match) return template;

  const [, prefix, numericPart, suffix] = match;
  const decimals = numericPart.includes(".") ? numericPart.split(".")[1].length : 0;
  const useGrouping = numericPart.includes(",");
  const formatted = value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping
  });

  return `${prefix}${formatted}${suffix}`;
}

function animateValue(node, nextValue) {
  const nextMatch = nextValue.match(/-?[\d,]+(?:\.\d+)?/);
  const currentMatch = node.textContent.match(/-?[\d,]+(?:\.\d+)?/);

  if (reducedMotion.matches || !nextMatch || !currentMatch) {
    node.textContent = nextValue;
    return;
  }

  const from = Number(currentMatch[0].replaceAll(",", ""));
  const to = Number(nextMatch[0].replaceAll(",", ""));
  if (!Number.isFinite(from) || !Number.isFinite(to)) {
    node.textContent = nextValue;
    return;
  }

  const previousAnimation = numberAnimations.get(node);
  if (previousAnimation) cancelAnimationFrame(previousAnimation);

  const start = performance.now();
  const duration = 680;

  function frame(now) {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    node.textContent = formatAnimatedValue(nextValue, from + (to - from) * eased);

    if (progress < 1) {
      numberAnimations.set(node, requestAnimationFrame(frame));
    } else {
      node.textContent = nextValue;
      numberAnimations.delete(node);
    }
  }

  numberAnimations.set(node, requestAnimationFrame(frame));
}

function updateComparisons(values) {
  const networkKeys = ["cmhk5g", "hkt5g", "three5g", "smt5g"];
  const networkValues = networkKeys.map((key) => Number(values[key].replaceAll(",", "")));
  const networkMax = Math.max(...networkValues);

  document.querySelectorAll(".network-bars i").forEach((bar, index) => {
    bar.style.setProperty("--value", `${Math.round((networkValues[index] / networkMax) * 100)}%`);
  });

  const revenueKeys = ["cmhkRevenue", "hktRevenue", "threeRevenue", "smtRevenue"];
  const revenueValues = revenueKeys.map((key) => Number(values[key]));
  const revenueMax = Math.max(...revenueValues);

  document.querySelectorAll(".revenue-compare > i").forEach((bar, index) => {
    bar.style.setProperty("--value", `${Math.round((revenueValues[index] / revenueMax) * 100)}%`);
  });
}

function setPeriod(period) {
  const values = demoData[period];
  if (!values) return;

  periodButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.period === period);
  });

  numberNodes.forEach((node) => {
    const nextValue = values[node.dataset.key];
    if (nextValue === undefined || node.textContent === nextValue) return;
    animateValue(node, nextValue);
  });

  updateComparisons(values);

  if (!reducedMotion.matches) {
    panels.forEach((panel, index) => {
      panel.animate(
        [
          { filter: "brightness(1)" },
          { filter: "brightness(1.1)" },
          { filter: "brightness(1)" }
        ],
        { duration: 520, delay: index * 45, easing: "ease-out" }
      );
    });
  }
}

periodButtons.forEach((button) => {
  button.addEventListener("click", () => setPeriod(button.dataset.period));
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
