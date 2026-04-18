from __future__ import annotations

import customtkinter as ctk

from ui.window_utils import set_textbox_value


def create_status_logs_dialog(
    parent,
    *,
    live_status_text,
    health_details_text,
    print_audit_text,
    errors_text,
    sync_now,
    reprint_last_label,
    export_diagnostics_bundle,
    present_dialog,
):
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Status & Logs")
    dialog.geometry("980x650")
    dialog.minsize(850, 540)

    action_bar = ctk.CTkFrame(dialog, fg_color="transparent")
    action_bar.pack(fill="x", padx=12, pady=(12, 6))

    tabview = ctk.CTkTabview(dialog)
    tabview.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    status_tab = tabview.add("Live Status")
    health_tab = tabview.add("Health")
    print_tab = tabview.add("Print Audit")
    error_tab = tabview.add("Errors")

    status_box = ctk.CTkTextbox(status_tab, wrap="none")
    status_box.pack(fill="both", expand=True, padx=8, pady=8)
    health_box = ctk.CTkTextbox(health_tab, wrap="none")
    health_box.pack(fill="both", expand=True, padx=8, pady=8)
    print_box = ctk.CTkTextbox(print_tab, wrap="none")
    print_box.pack(fill="both", expand=True, padx=8, pady=8)
    error_box = ctk.CTkTextbox(error_tab, wrap="none")
    error_box.pack(fill="both", expand=True, padx=8, pady=8)

    def refresh():
        set_textbox_value(status_box, live_status_text())
        set_textbox_value(health_box, health_details_text())
        set_textbox_value(print_box, print_audit_text())
        set_textbox_value(error_box, errors_text())

    def run_sync_now():
        try:
            sync_now()
        finally:
            refresh()

    ctk.CTkButton(action_bar, text="Refresh", width=120, command=refresh).pack(side="left", padx=(0, 8))
    ctk.CTkButton(action_bar, text="Sync Now", width=120, command=run_sync_now).pack(side="left", padx=(0, 8))
    ctk.CTkButton(
        action_bar,
        text="Reprint Last Label",
        width=160,
        command=lambda: (reprint_last_label(), refresh()),
    ).pack(side="left", padx=(0, 8))
    ctk.CTkButton(
        action_bar,
        text="Export Diagnostics",
        width=160,
        command=export_diagnostics_bundle,
    ).pack(side="left", padx=(0, 8))
    ctk.CTkButton(action_bar, text="Close", width=120, command=dialog.destroy).pack(side="right")

    refresh()
    try:
        tabview.set("Live Status")
    except Exception:
        pass
    present_dialog(dialog)
    return dialog
