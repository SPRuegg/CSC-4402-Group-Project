const tabs = document.querySelectorAll(".nav-item");
tabs.forEach((tab) =>
  tab.addEventListener("click", () => {
    tabs.forEach((item) => {
      item.classList.remove("active");
      item.removeAttribute("aria-current");
    });
    tab.classList.add("active");
    tab.setAttribute("aria-current", "page");
  })
);

const root = document.documentElement;
const toggleBtn = document.getElementById("theme-toggle");
const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

const updateToggleState = (theme) => {
  const isDark = theme === "dark";
  toggleBtn.setAttribute(
    "aria-label",
    isDark ? "Switch to light mode" : "Switch to dark mode"
  );
  toggleBtn.setAttribute("aria-pressed", String(isDark));
};

updateToggleState(root.dataset.theme);

toggleBtn.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
  root.dataset.theme = nextTheme;
  localStorage.setItem("theme", nextTheme);
  updateToggleState(nextTheme);
});

mediaQuery.addEventListener("change", (event) => {
  if (!localStorage.getItem("theme")) {
    const systemTheme = event.matches ? "dark" : "light";
    root.dataset.theme = systemTheme;
    updateToggleState(systemTheme);
  }
});
