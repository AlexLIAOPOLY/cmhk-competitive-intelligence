const demoData = {
  "2024": {
    siteTotal: "3,100", siteGrowth: "+5.6%",
    cmhk5g: "1,280", hkt5g: "1,510", three5g: "1,120", smt5g: "1,030",
    cmhkCompute: "1,120",
    mobileUsers: "309.6", mobileArpu: "129.8",
    homeUsers: "71.2", homeArpu: "181.6",
    contractValue: "14.2", businessUsers: "31.5",
    stores: "121", appMau: "176",
    cmhkRevenue: "84.1", ebitda: "29.4", ebitdaMargin: "34.9", netProfit: "9.8"
  },
  "2025": {
    siteTotal: "3,400", siteGrowth: "+7.1%",
    cmhk5g: "1,460", hkt5g: "1,670", three5g: "1,260", smt5g: "1,140",
    cmhkCompute: "1,420",
    mobileUsers: "328.4", mobileArpu: "134.2",
    homeUsers: "79.8", homeArpu: "190.4",
    contractValue: "16.5", businessUsers: "35.1",
    stores: "130", appMau: "198",
    cmhkRevenue: "90.2", ebitda: "31.9", ebitdaMargin: "35.3", netProfit: "11.1"
  },
  "2026": {
    siteTotal: "3,700", siteGrowth: "+8.4%",
    cmhk5g: "1,620", hkt5g: "1,810", three5g: "1,390", smt5g: "1,260",
    cmhkCompute: "1,680",
    mobileUsers: "342.8", mobileArpu: "138.6",
    homeUsers: "86.4", homeArpu: "198.2",
    contractValue: "18.6", businessUsers: "38.2",
    stores: "138", appMau: "218",
    cmhkRevenue: "96.8", ebitda: "34.8", ebitdaMargin: "35.9", netProfit: "12.4"
  }
};

const numberNodes = [...document.querySelectorAll("[data-key]")];
const periodButtons = [...document.querySelectorAll("[data-period]")];

function setPeriod(period) {
  const values = demoData[period];
  if (!values) return;

  periodButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.period === period);
  });

  numberNodes.forEach((node) => {
    const nextValue = values[node.dataset.key];
    if (nextValue === undefined || node.textContent === nextValue) return;

    node.animate(
      [
        { opacity: 1, transform: "translateY(0)" },
        { opacity: 0, transform: "translateY(-5px)" },
        { opacity: 0, transform: "translateY(5px)" },
        { opacity: 1, transform: "translateY(0)" }
      ],
      { duration: 360, easing: "ease-out" }
    );

    window.setTimeout(() => {
      node.textContent = nextValue;
    }, 170);
  });
}

periodButtons.forEach((button) => {
  button.addEventListener("click", () => setPeriod(button.dataset.period));
});
