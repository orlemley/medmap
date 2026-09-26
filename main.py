import tkinter as tk
from PIL import Image, ImageTk

def start_screen():
    # Create the main window
    root = tk.Tk()
    root.title("Start Screen")
    root.geometry("800x600")

    # Load and display the background image
    bg_image = Image.open("background.jpg")  # Replace with your image path
    bg_image = bg_image.resize((800, 600), Image.ANTIALIAS)
    bg_photo = ImageTk.PhotoImage(bg_image)

    bg_label = tk.Label(root, image=bg_photo)
    bg_label.place(x=0, y=0, relwidth=1, relheight=1)

    # Create a start button
    start_button = tk.Button(root, text="Start", font=("Arial", 24), command=lambda: print("Game Started!"))
    start_button.pack(pady=20)

    # Run the main loop
    root.mainloop()