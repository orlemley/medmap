const meta = document.getElementById("meta");
const startButton = document.getElementById("start");
const cards = document.querySelectorAll(".card");
const defaultMessage = meta.textContent;

// Clicking a metric card shows its detail in the status line; clicking again clears it
cards.forEach((card) => {
  card.addEventListener("click", () => {
    const wasSelected = card.classList.contains("selected");
    cards.forEach((c) => c.classList.remove("selected"));

    if (wasSelected) {
      meta.textContent = defaultMessage;
    } else {
      card.classList.add("selected");
      meta.textContent = card.dataset.detail;
    }
  });
});

startButton.addEventListener("click", () => {
  console.log("Game Started!");
  meta.textContent = "Started. Loading placement data...";
  startButton.disabled = true;
  startButton.textContent = "Started";
});
