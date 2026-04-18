from __future__ import annotations

import customtkinter as ctk


class StartupScreen(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        parent.title("Initializing...")
        parent.geometry("500x200")
        parent.resizable(False, False)

        window_width = 500
        window_height = 200
        screen_width = parent.winfo_screenwidth()
        screen_height = parent.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        parent.geometry(f'{window_width}x{window_height}+{x}+{y}')

        self.configure(fg_color=parent.cget("fg_color"))
        self.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(
            self,
            text="Fluidra Manufacturing Solution",
            font=("Arial", 20, "bold")
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="nsew")

        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.status_frame.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="Starting up...",
            font=("Arial", 14)
        )
        self.status_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.progress = ctk.CTkProgressBar(self.status_frame, mode='indeterminate')
        self.progress.grid(row=1, column=0, padx=10, pady=10, sticky="ew", columnspan=2)
        self.progress.start()

        self.version_label = ctk.CTkLabel(
            self,
            text="FMS v7.10",
            font=("Arial", 10, "italic"),
            text_color="gray"
        )
        self.version_label.grid(row=2, column=0, pady=(0, 10))

        self.tkraise()
        parent.lift()
        parent.attributes('-topmost', True)
        parent.after_idle(parent.attributes, '-topmost', False)

    def update_status(self, message):
        self.status_label.configure(text=message)
        self.tkraise()
        self.update_idletasks()
