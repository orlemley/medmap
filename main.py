import tkinter as tk
from PIL import Image, ImageTk


def start_screen():
    root = tk.Tk()
    root.title("Optimal Hospital Placer")
    root.geometry("920x620")
    root.minsize(820, 560)
    root.configure(bg="#0b1220")

    background_image = None
    try:
        img = Image.open("background.jpg")
        img = img.resize((920, 620), Image.Resampling.LANCZOS)
        background_image = ImageTk.PhotoImage(img)
        bg_label = tk.Label(root, image=background_image)
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except FileNotFoundError:
        root.configure(bg="#0b1220")

    panel = tk.Frame(
        root,
        bg="#111827",
        bd=0,
        highlightthickness=0,
        padx=34,
        pady=34,
    )
    panel.place(relx=0.5, rely=0.5, anchor="center", width=620, height=420)

    badge = tk.Label(
        panel,
        text="Healthcare Strategy Tool",
        font=("Segoe UI", 11, "bold"),
        bg="#1d4ed8",
        fg="#eff6ff",
        padx=14,
        pady=7,
        relief="flat",
    )
    badge.pack(anchor="w")

    title = tk.Label(
        panel,
        text="Optimal Hospital Placer",
        font=("Segoe UI", 30, "bold"),
        bg="#111827",
        fg="#f8fafc",
        justify="left",
    )
    title.pack(anchor="w", pady=(18, 8))

    subtitle = tk.Label(
        panel,
        text="Plan smarter hospital placement using access, demand, and rural coverage data.",
        font=("Segoe UI", 15),
        bg="#111827",
        fg="#cbd5e1",
        justify="left",
        wraplength=520,
    )
    subtitle.pack(anchor="w")

    meta = tk.Label(
        panel,
        text="Ready to optimize care access across communities.",
        font=("Segoe UI", 11, "bold"),
        bg="#111827",
        fg="#93c5fd",
        justify="left",
    )
    meta.pack(anchor="w", pady=(18, 20))

    metrics = tk.Frame(panel, bg="#111827")
    metrics.pack(fill="x", pady=(0, 22))

    metric_conf = [
        ("Access", "Coverage zones"),
        ("Demand", "Population needs"),
        ("Rural", "Underserved areas"),
    ]

    for label, value in metric_conf:
        card = tk.Frame(metrics, bg="#1f2937", padx=18, pady=14, width=150, height=72)
        card.pack(side="left", expand=True, fill="x", padx=(0, 12))
        card.pack_propagate(False)

        tk.Label(card, text=label, font=("Segoe UI", 10, "bold"), bg="#1f2937", fg="#93c5fd").pack(anchor="w")
        tk.Label(card, text=value, font=("Segoe UI", 12), bg="#1f2937", fg="#f8fafc").pack(anchor="w", pady=(6, 0))

    button_row = tk.Frame(panel, bg="#111827")
    button_row.pack(fill="x")

    def on_enter(event):
        start_button.config(bg="#1d4ed8")

    def on_leave(event):
        start_button.config(bg="#2563eb")

    start_button = tk.Button(
        button_row,
        text="Start",
        font=("Segoe UI", 18, "bold"),
        bg="#2563eb",
        fg="#ffffff",
        activebackground="#1d4ed8",
        activeforeground="#ffffff",
        bd=0,
        padx=28,
        pady=12,
        cursor="hand2",
        command=lambda: print("Game Started!"),
    )
    start_button.pack(anchor="w")
    start_button.bind("<Enter>", on_enter)
    start_button.bind("<Leave>", on_leave)

    root.mainloop()


if __name__ == "__main__":
    start_screen()