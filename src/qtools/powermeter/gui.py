#!/usr/bin/env python3
"""Optical powermeter GUI for QOLab.

Architecture
------------
The GUI is a pure **view** — it owns display, layout, and user interaction.
All measurement logic (EMA, auto-range, voltage-to-power calibration) lives
inside the backend device.  The update loop simply calls::

    power = device.get_power()
    voltage = device.get_voltage()   # if available

Device lifecycle — long-lived connection::

    Start  → get_device(address, backend)  → .connect()    → running
    Stop   → .reset() → .disconnect()      → powermeter = None

Backend interface::

    get_power()     → float    read + smooth + auto-range + calibrate
    get_voltage()   → float    raw photodiode voltage (S15 only)
    set_wavelength(wl)         update wavelength + auto-switch cal file
    set_range(idx)             switch sense-resistor (1-5)
    load_calibration_file(path)
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import serial.tools.list_ports

from qtools.powermeter.connection import get_device
from qtools.powermeter.backends.thorlabs import ThorlabsPowerMeter

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CALIBRATION_FILES = {
    "s5106": os.path.join(_pkg_dir, "backends", "s15", "s5106_interpolated.cal"),
    "fdg50": os.path.join(_pkg_dir, "backends", "s15", "fdg50_interpolated.cal"),
}
REFRESH_MS = 100
MIN_WAVELENGTH = 340
MAX_WAVELENGTH = 2000


class GuiQolab:
    """Tkinter-based real-time optical powermeter monitor."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QOLab Optical Powermeter")
        self.root.resizable(False, False)

        # ---- UI state -------------------------------------------------------
        self.backend_value = tk.StringVar(value="s15")
        self.port_value = tk.StringVar()
        self.calibration_choice = tk.StringVar(value="s5106")
        self.calibration_path: str = DEFAULT_CALIBRATION_FILES["s5106"]
        self.range_value = tk.IntVar(value=1)
        self.autorange_value = tk.BooleanVar(value=True)
        self.wavelength_value = tk.IntVar(value=780)
        self.status_text = tk.StringVar(value="Ready")
        self.voltage_text = tk.StringVar(value="Voltage: N/A")
        self.power_text = tk.StringVar(value="N/A")

        # ---- device + loop state -------------------------------------------
        self.powermeter = None
        self.running = False

        # ---- plot buffers --------------------------------------------------
        self.plot_x = list(range(100))
        self.plot_y = [0.0] * 100

        self._build_ui()
        self._refresh_ports()

        self.wavelength_value.trace_add("write", self._on_wavelength_changed)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(REFRESH_MS, self._update_loop)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Row 0: Backend & Port
        ttk.Label(main_frame, text="Backend:").grid(row=0, column=0, sticky="w")
        self.backend_combo = ttk.Combobox(
            main_frame, textvariable=self.backend_value,
            values=["s15", "mock", "lbtek", "thorlabs"],
            state="readonly", width=10,
        )
        self.backend_combo.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.backend_combo.bind("<<ComboboxSelected>>", lambda _: self._refresh_ports())

        ttk.Label(main_frame, text="Port:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.port_combo = ttk.Combobox(
            main_frame, textvariable=self.port_value, width=22, state="readonly",
        )
        self.port_combo.grid(row=0, column=3, sticky="we", padx=(4, 0))
        ttk.Button(main_frame, text="Refresh", command=self._refresh_ports).grid(
            row=0, column=4, padx=(8, 0),
        )

        # Row 1: Calibration
        ttk.Label(main_frame, text="Calibration:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        cal_values = ["s5106", "fdg50", "custom"]
        self.cal_combo = ttk.Combobox(
            main_frame, textvariable=self.calibration_choice,
            values=cal_values, state="readonly", width=10,
        )
        self.cal_combo.grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(8, 0))
        self.cal_combo.bind("<<ComboboxSelected>>", self._on_calibration_choice)
        ttk.Button(main_frame, text="Browse...", command=self._browse_calibration).grid(
            row=1, column=4, padx=(8, 0), pady=(8, 0),
        )
        self.cal_path_label = ttk.Label(
            main_frame, text=self.calibration_path, wraplength=480, font=("Arial", 9),
        )
        self.cal_path_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

        # Row 3: Range
        ttk.Label(main_frame, text="Range:").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.range_combo = ttk.Combobox(
            main_frame, textvariable=self.range_value,
            values=[1, 2, 3, 4, 5], state="readonly", width=4,
        )
        self.range_combo.grid(row=3, column=1, sticky="w", padx=(4, 0), pady=(12, 0))
        self.range_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_range())
        self.autorange_check = ttk.Checkbutton(
            main_frame, text="Auto range", variable=self.autorange_value,
            command=self._on_autorange_toggle,
        )
        self.autorange_check.grid(row=3, column=2, columnspan=2, sticky="w", pady=(12, 0))

        # Row 4: Wavelength
        ttk.Label(main_frame, text="Wavelength (nm):").grid(row=4, column=0, sticky="w", pady=(12, 0))
        wl_frame = ttk.Frame(main_frame)
        wl_frame.grid(row=4, column=1, columnspan=4, sticky="w", pady=(12, 0))
        self.wavelength_entry = ttk.Entry(
            wl_frame, textvariable=self.wavelength_value, width=8, justify="center",
        )
        self.wavelength_entry.grid(row=0, column=0)
        ttk.Button(wl_frame, text="-100", width=4, command=lambda: self._change_wavelength(-100)).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(wl_frame, text="+100", width=4, command=lambda: self._change_wavelength(100)).grid(row=0, column=2, padx=(4, 0))
        ttk.Button(wl_frame, text="-10", width=4, command=lambda: self._change_wavelength(-10)).grid(row=0, column=3, padx=(4, 0))
        ttk.Button(wl_frame, text="+10", width=4, command=lambda: self._change_wavelength(10)).grid(row=0, column=4, padx=(4, 0))

        # Row 5: Actions
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=5, column=0, columnspan=5, pady=(14, 0), sticky="we")
        self.start_button = ttk.Button(action_frame, text="Start", command=self._toggle_device)
        self.start_button.grid(row=0, column=0, sticky="we")
        ttk.Button(
            action_frame, text="Reload calibration",
            command=lambda: self._apply_calibration_to_device(),
        ).grid(row=0, column=1, padx=(8, 0), sticky="we")

        ttk.Separator(main_frame, orient="horizontal").grid(
            row=6, column=0, columnspan=5, sticky="we", pady=(12, 12),
        )

        # Row 7: Plot
        plot_frame = ttk.Frame(main_frame)
        plot_frame.grid(row=7, column=0, columnspan=5, sticky="nsew")
        self.plot_figure = Figure(figsize=(6.2, 3.15), dpi=100, constrained_layout=True)
        self.plot_ax = self.plot_figure.add_subplot(111)
        self.plot_ax.set_xlabel("Samples (100 ms per point)")
        self.plot_ax.grid(True, linestyle="--", alpha=0.4)
        self.plot_line, = self.plot_ax.plot(self.plot_x, self.plot_y, color="tab:red")
        self.plot_canvas = FigureCanvasTkAgg(self.plot_figure, master=plot_frame)
        self.plot_canvas.draw()
        self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Rows 8-10: Readouts
        ttk.Label(main_frame, textvariable=self.voltage_text, font=("Arial", 20, "bold")).grid(
            row=8, column=0, columnspan=5, sticky="w",
        )
        ttk.Label(main_frame, text="Power:", font=("Arial", 40, "bold")).grid(
            row=9, column=0, sticky="w",
        )
        ttk.Label(
            main_frame, textvariable=self.power_text,
            font=("Arial", 40, "bold"), foreground="red",
        ).grid(row=9, column=1, columnspan=4, sticky="w")
        ttk.Label(main_frame, textvariable=self.status_text, foreground="blue").grid(
            row=10, column=0, columnspan=5, sticky="w", pady=(12, 0),
        )

    # ------------------------------------------------------------------
    # Port discovery
    # ------------------------------------------------------------------

    def _refresh_ports(self) -> None:
        backend = self.backend_value.get()
        display_ports: list[str] = []

        if backend == "mock":
            display_ports = ["MOCK0", "MOCK1"]
        elif backend == "thorlabs":
            display_ports = ThorlabsPowerMeter.list_devices()
            if not display_ports:
                display_ports = ["No VISA devices found"]
        else:  # s15 or lbtek
            exclude_kw = {"bluetooth", "incoming", "wlan"}
            ports = list(serial.tools.list_ports.comports())
            for port in ports:
                dev = port.device.lower()
                desc = (port.description or "").lower()
                if any(kw in dev or kw in desc for kw in exclude_kw):
                    continue
                display_ports.append(f"{port.device} ({port.description})")
            if not display_ports:
                display_ports = ["No serial devices found"]

        self.port_combo["values"] = display_ports
        self.port_value.set(display_ports[0])
        if backend != "mock" and ("No serial" in display_ports[0] or "No VISA" in display_ports[0]):
            self.start_button.state(["disabled"])
        else:
            self.start_button.state(["!disabled"])

    # ------------------------------------------------------------------
    # Calibration (GUI stores path only; device owns the data)
    # ------------------------------------------------------------------

    def _on_calibration_choice(self, event=None) -> None:
        choice = self.calibration_choice.get()
        if choice in DEFAULT_CALIBRATION_FILES:
            self.calibration_path = DEFAULT_CALIBRATION_FILES[choice]
            self.cal_path_label.config(text=self.calibration_path)
            self._apply_calibration_to_device()
        else:
            self._browse_calibration()

    def _browse_calibration(self) -> None:
        path = filedialog.askopenfilename(
            title="Select calibration file",
            filetypes=[("Calibration files", "*.cal *.json *.txt"), ("All files", "*")],
        )
        if path:
            self.calibration_path = path
            self.calibration_choice.set("custom")
            self.cal_path_label.config(text=self.calibration_path)
            self._apply_calibration_to_device()

    def _apply_calibration_to_device(self) -> None:
        """Push the selected calibration file to the connected device."""
        if not self.powermeter or not self.running:
            return
        try:
            self.powermeter.load_calibration_file(self.calibration_path)
            self._set_status(f"Calibration: {os.path.basename(self.calibration_path)}")
        except Exception as exc:
            self._set_status(f"Calibration error: {exc}", error=True)

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    def _toggle_device(self) -> None:
        if self.running:
            self._stop_device()
        else:
            self._start_device()

    def _start_device(self) -> None:
        port_label = self.port_value.get()
        backend = self.backend_value.get()
        address = port_label.split(" (")[0] if " (" in port_label else port_label

        if backend != "mock" and ("No serial" in address or "No VISA" in address):
            self._set_status("No valid port selected", error=True)
            return

        try:
            self.powermeter = get_device(backend, address)
            self.powermeter.connect()

            # Push calibration + wavelength to device
            self._apply_calibration_to_device()
            try:
                self.powermeter.set_wavelength(float(self.wavelength_value.get()))
            except Exception:
                pass

            self.running = True
            self.start_button.config(text="Stop")
            self._apply_range()
            self._set_status(f"Connected to {address} ({backend})")
        except Exception as exc:
            self.powermeter = None
            self.running = False
            self._set_status(f"Failed to open device: {exc}", error=True)
            messagebox.showerror("Connection error", str(exc))

    def _stop_device(self) -> None:
        if self.powermeter:
            try:
                self.powermeter.reset()
            except Exception:
                pass
            try:
                self.powermeter.disconnect()
            except Exception:
                pass
        self.powermeter = None
        self.running = False
        self.start_button.config(text="Start")
        self.voltage_text.set("Voltage: N/A")
        self.power_text.set("Power: N/A")
        self._set_status("Stopped")

    def _apply_range(self) -> None:
        if not self.running or not self.powermeter:
            return
        try:
            if self.autorange_value.get():
                self.powermeter.set_range(0)    # 0 = enable auto-range
            else:
                self.powermeter.set_range(int(self.range_value.get()))
        except Exception as exc:
            self._set_status(f"Range error: {exc}", error=True)

    def _on_autorange_toggle(self) -> None:
        """Propagate auto-range checkbox changes to the device."""
        if self.running and self.powermeter:
            if self.autorange_value.get():
                self.powermeter.set_range(0)
            else:
                self.powermeter.set_range(int(self.range_value.get()))

    # ------------------------------------------------------------------
    # Wavelength
    # ------------------------------------------------------------------

    def _change_wavelength(self, delta: int) -> None:
        try:
            new = self.wavelength_value.get() + delta
            new = max(MIN_WAVELENGTH, min(MAX_WAVELENGTH, new))
            self.wavelength_value.set(new)
            self._push_wavelength(new)
        except Exception:
            pass

    def _on_wavelength_changed(self, *args) -> None:
        try:
            wl = self.wavelength_value.get()
        except Exception:
            return
        if wl < MIN_WAVELENGTH or wl > MAX_WAVELENGTH:
            return
        # Auto-switch default calibration based on wavelength
        if self.calibration_choice.get() != "custom":
            if wl >= 1100:
                if self.calibration_choice.get() != "fdg50":
                    self.calibration_choice.set("fdg50")
                    self.calibration_path = DEFAULT_CALIBRATION_FILES["fdg50"]
                    self.cal_path_label.config(text=self.calibration_path)
            else:
                if self.calibration_choice.get() != "s5106":
                    self.calibration_choice.set("s5106")
                    self.calibration_path = DEFAULT_CALIBRATION_FILES["s5106"]
                    self.cal_path_label.config(text=self.calibration_path)
        self._push_wavelength(wl)

    def _push_wavelength(self, wl: float) -> None:
        """Forward wavelength to device; device handles cal switching internally."""
        if self.running and self.powermeter:
            try:
                self.powermeter.set_wavelength(wl)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main update loop  (pure view — delegates to device)
    # ------------------------------------------------------------------

    def _update_loop(self) -> None:
        if self.running and self.powermeter:
            try:
                power = self.powermeter.get_power()

                if hasattr(self.powermeter, "get_voltage"):
                    # Prefer values cached by get_power() — no extra serial I/O.
                    volt = getattr(self.powermeter, "last_voltage", None)
                    if volt is None:
                        volt = getattr(self.powermeter, "smoothed_voltage", None)
                    if volt is None:
                        volt = self.powermeter.get_voltage()

                    r_idx = getattr(self.powermeter, "last_range", None)
                    if r_idx is None and hasattr(self.powermeter, "get_range"):
                        try:
                            r_idx = self.powermeter.get_range()
                        except Exception:
                            r_idx = None

                    # Keep the range combo in sync under auto-range so the UI
                    # always shows which sense-resistor is currently active.
                    if r_idx is not None and self.autorange_value.get():
                        try:
                            if int(self.range_value.get()) != int(r_idx):
                                self.range_value.set(int(r_idx))
                        except Exception:
                            pass

                    if r_idx is not None:
                        self.voltage_text.set(f"Voltage: {volt:.4f} V  |  Range: {r_idx}")
                    else:
                        self.voltage_text.set(f"Voltage: {volt:.4f} V")
                else:
                    try:
                        self.powermeter.set_wavelength(float(self.wavelength_value.get()))
                    except Exception:
                        pass
                    self.voltage_text.set("Voltage: N/A (Direct Power)")

                self.power_text.set(self._format_power(power))
                self._update_plot(power)
            except Exception as exc:
                self._set_status(f"Read error: {exc}", error=True)
        self.root.after(REFRESH_MS, self._update_loop)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_power(power: float) -> str:
        if power >= 1:
            return f"{power:.2f} W"
        if power >= 1e-3:
            return f"{power * 1e3:.2f} mW"
        if power >= 1e-6:
            return f"{power * 1e6:.2f} μW"
        return f"{power * 1e9:.2f} nW"

    def _update_plot(self, power: float) -> None:
        self.plot_y.pop(0)
        self.plot_y.append(power)
        self.plot_line.set_ydata(self.plot_y)
        ymin, ymax = min(self.plot_y), max(self.plot_y)
        if ymin == ymax:
            ymin -= 1e-9
            ymax += 1e-9
        self.plot_ax.set_ylim(ymin * 0.9, ymax * 1.1)
        self.plot_canvas.draw_idle()

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_text.set(text)

    def _on_close(self) -> None:
        self._stop_device()
        self.root.destroy()


def run_gui() -> None:
    root = tk.Tk()
    GuiQolab(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
