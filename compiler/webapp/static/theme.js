// Runs before the page paints so the saved theme never flashes.
(function () {
  try {
    var saved = localStorage.getItem("excel-compiler-theme");
    if (saved === "light") document.documentElement.setAttribute("data-theme", "light");
  } catch (error) { /* storage can be blocked; the default theme still works */ }
})();
