const demoData = {
  "2024": {
    cmhk4g: "1,820", cmhk5g: "1,280", hkt4g: "2,210", hkt5g: "1,510",
    three4g: "1,690", three5g: "1,120", smt4g: "1,560", smt5g: "1,030",
    cmhkCompute: "1,120", hktCompute: "960", threeCompute: "720", smtCompute: "630",
    mobileUsers: "309.6", mobileArpu: "129.8", homeUsers: "71.2", homeArpu: "181.6",
    contractValue: "14.2", businessUsers: "31.5", stores: "121", appMau: "176",
    cmhkRevenue: "84.1", hktRevenue: "77.8", threeRevenue: "52.1", smtRevenue: "49.3",
    ebitda: "29.4", ebitdaMargin: "34.9", netProfit: "9.8"
  },
  "2025": {
    cmhk4g: "1,940", cmhk5g: "1,460", hkt4g: "2,320", hkt5g: "1,670",
    three4g: "1,770", three5g: "1,260", smt4g: "1,640", smt5g: "1,140",
    cmhkCompute: "1,420", hktCompute: "1,180", threeCompute: "890", smtCompute: "770",
    mobileUsers: "328.4", mobileArpu: "134.2", homeUsers: "79.8", homeArpu: "190.4",
    contractValue: "16.5", businessUsers: "35.1", stores: "130", appMau: "198",
    cmhkRevenue: "90.2", hktRevenue: "80.6", threeRevenue: "54.8", smtRevenue: "50.7",
    ebitda: "31.9", ebitdaMargin: "35.3", netProfit: "11.1"
  },
  "2026": {
    cmhk4g: "2,080", cmhk5g: "1,620", hkt4g: "2,420", hkt5g: "1,810",
    three4g: "1,850", three5g: "1,390", smt4g: "1,720", smt5g: "1,260",
    cmhkCompute: "1,680", hktCompute: "1,420", threeCompute: "1,080", smtCompute: "920",
    mobileUsers: "342.8", mobileArpu: "138.6", homeUsers: "86.4", homeArpu: "198.2",
    contractValue: "18.6", businessUsers: "38.2", stores: "138", appMau: "218",
    cmhkRevenue: "96.8", hktRevenue: "84.2", threeRevenue: "57.4", smtRevenue: "52.6",
    ebitda: "34.8", ebitdaMargin: "35.9", netProfit: "12.4"
  }
};

const numberNodes = [...document.querySelectorAll("[data-key]")];
const periodButtons = [...document.querySelectorAll("[data-period]")];
const clock = document.querySelector("#dashboardClock");
const refreshButton = document.querySelector("#refreshDemo");
const lastRefresh = document.querySelector("#lastRefresh");

function updateClock() {
  clock.textContent = new Intl.DateTimeFormat("zh-HK", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date());
}

function setPeriod(period) {
  const values = demoData[period];
  if (!values) return;
  periodButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.period === period));
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
    window.setTimeout(() => { node.textContent = nextValue; }, 170);
  });
}

periodButtons.forEach((button) => {
  button.addEventListener("click", () => setPeriod(button.dataset.period));
});

document.querySelectorAll(".panel-tabs").forEach((tabList) => {
  tabList.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    tabList.querySelectorAll("button").forEach((item) => item.classList.toggle("is-active", item === button));
  });
});

refreshButton.addEventListener("click", () => {
  refreshButton.classList.add("is-refreshing");
  lastRefresh.textContent = "最近刷新：更新中";
  window.setTimeout(() => {
    refreshButton.classList.remove("is-refreshing");
    lastRefresh.textContent = "最近刷新：刚刚";
  }, 760);
});

updateClock();
window.setInterval(updateClock, 1000);
