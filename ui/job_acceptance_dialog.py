from __future__ import annotations

import customtkinter as ctk

from job_execution.models import JobContext


def show_job_acceptance_dialog(
    parent,
    job: JobContext,
    *,
    accept_callback,
    cancel_callback=None,
    present_dialog=None,
):
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Accept Proposed Job")
    dialog.geometry("520x420")
    dialog.resizable(False, False)

    container = ctk.CTkFrame(dialog)
    container.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(
        container,
        text="Accept Teraoka Job",
        font=("Arial", 20, "bold"),
    ).pack(anchor="w", pady=(4, 12))

    fields = [
        ("Job ID", job.display_job_id),
        ("Sequence", job.display_sequence),
        ("Product Code", job.display_product_code),
        ("Target Quantity", job.display_target_quantity),
        ("Actual Quantity", str(job.actual_quantity) if job.actual_quantity is not None else "-"),
        ("Remaining Quantity", str(job.remaining_quantity) if job.remaining_quantity is not None else "-"),
        ("% Complete", f"{job.percent_complete:.1f}%" if job.percent_complete is not None else "-"),
        ("Workcenter", job.workcenter or "-"),
    ]
    if job.priority:
        fields.append(("Priority", job.priority))

    grid = ctk.CTkFrame(container, fg_color="transparent")
    grid.pack(fill="x", pady=(0, 14))
    grid.grid_columnconfigure(1, weight=1)
    for row, (label, value) in enumerate(fields):
        ctk.CTkLabel(grid, text=f"{label}:", font=("Arial", 13, "bold"), anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=4
        )
        ctk.CTkLabel(grid, text=str(value or "-"), font=("Arial", 13), anchor="w").grid(
            row=row, column=1, sticky="we", pady=4
        )

    ctk.CTkLabel(
        container,
        text="Accepting this job will set the logger's active production context and select the job product.",
        font=("Arial", 12),
        text_color="gray",
        wraplength=460,
        justify="left",
    ).pack(anchor="w", pady=(0, 16))

    button_bar = ctk.CTkFrame(container, fg_color="transparent")
    button_bar.pack(fill="x", pady=(4, 0))

    def accept():
        try:
            accept_callback(job)
        finally:
            dialog.destroy()

    def cancel():
        if cancel_callback is not None:
            cancel_callback(job)
        dialog.destroy()

    ctk.CTkButton(button_bar, text="Accept Job", command=accept, width=150).pack(side="right", padx=(8, 0))
    ctk.CTkButton(button_bar, text="Not Now", command=cancel, width=120, fg_color="gray35").pack(side="right")

    dialog.protocol("WM_DELETE_WINDOW", cancel)
    if present_dialog is not None:
        present_dialog(dialog)
    return dialog
