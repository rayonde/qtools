#!/usr/bin/env python3
"""
modeling.py
-----------
Jones matrix simulation and intensity calculation for polarization systems.
Provides a generic multi-element Jones calculus for arbitrary waveplate sequences.
"""

import numpy as np
from typing import List


class JonesModel:
    """Jones matrix calculations for polarization retarders."""

    @staticmethod
    def rotation(theta_deg: float) -> np.ndarray:
        """Linear polarization basis rotation matrix."""
        theta = np.radians(theta_deg)
        return np.array([
            [np.cos(theta), -np.sin(theta)],
            [np.sin(theta), np.cos(theta)]
        ], dtype=complex)

    @staticmethod
    def retarder(theta_deg: float, delta_rad: float) -> np.ndarray:
        """General linear retarder with fast axis angle and retardance delta."""
        phi_fast = -delta_rad / 2
        phi_slow = delta_rad / 2
        J_diag = np.array([
            [np.exp(1j * phi_fast), 0.0],
            [0.0, np.exp(1j * phi_slow)]
        ], dtype=complex)
        R = JonesModel.rotation(theta_deg)
        return R.T @ J_diag @ R

    @classmethod
    def qwp(cls, theta_deg: float) -> np.ndarray:
        """Quarter-wave plate Jones matrix."""
        theta = np.radians(theta_deg)
        c = np.cos(theta)
        s = np.sin(theta)
        m00 = c**2 * np.exp(1j * np.pi / 4) + s**2 * np.exp(-1j * np.pi / 4)
        m01 = c * s * (np.exp(1j * np.pi / 4) - np.exp(-1j * np.pi / 4))
        m10 = m01
        m11 = s**2 * np.exp(1j * np.pi / 4) + c**2 * np.exp(-1j * np.pi / 4)
        return np.array([[m00, m01], [m10, m11]])

    @classmethod
    def hwp(cls, theta_deg: float) -> np.ndarray:
        """Half-wave plate Jones matrix."""
        theta = np.radians(theta_deg)
        m00 = np.cos(2 * theta)
        m01 = np.sin(2 * theta)
        m10 = m01
        m11 = -np.cos(2 * theta)
        return np.array([[m00, m01], [m10, m11]])

    @classmethod
    def system_matrix(cls, waveplates: List[str], angles: List[float]) -> np.ndarray:
        """
        Compute cumulative Jones matrix of the system:
        J_sys = J_n * J_{n-1} * ... * J_1 (multiplied in reverse order of propagation).
        angles are simulated fast axis angles.
        """
        J = np.eye(2, dtype=complex)
        for wp, ang in zip(waveplates, angles):
            wp_type = wp.upper()
            if wp_type == "QWP":
                J_wp = cls.qwp(ang)
            elif wp_type == "HWP":
                J_wp = cls.hwp(ang)
            elif wp_type == "RETARDER":
                # Expect angle list to carry [theta_deg, delta_rad] pairs for RETARDER entries.
                if not isinstance(ang, (tuple, list)):
                    raise ValueError(
                        "RETARDER entries must supply (theta_deg, delta_rad)"
                    )
                theta_deg, delta_rad = ang
                J_wp = cls.retarder(theta_deg, delta_rad)
            else:
                J_wp = np.eye(2, dtype=complex)
            J = J_wp @ J
        return J

    @classmethod
    def intensity(
        cls,
        waveplates: List[str],
        angles: List[float],
        alpha: float,
        beta: float,
        analyzer_deg: float = 0.0
    ) -> float:
        """
        Calculate transmitted intensity for a normalized input state:
        E_in = [cos(alpha), sin(alpha) * exp(j * beta)]
        Projected onto a linear polarizer at analyzer_deg.
        """
        E_in = np.array([np.cos(alpha), np.sin(alpha) * np.exp(1j * beta)])
        J = cls.system_matrix(waveplates, angles)
        E_out = J @ E_in

        ana_rad = np.radians(analyzer_deg)
        proj = np.array([np.cos(ana_rad), np.sin(ana_rad)])

        amplitude = np.dot(proj, E_out)
        return float(np.abs(amplitude) ** 2)


def map_servo_to_plate(
    servo_deg: float,
    scale: float,
    offset: float,
    a_wobble: float = 0.0,
    b_wobble: float = 0.0
) -> float:
    """
    Map physical servo angle to simulated optical waveplate fast axis angle,
    with optional sinusoidal wobble correction terms.
    """
    return (
        scale * servo_deg
        + offset
        + a_wobble * np.sin(np.radians(servo_deg))
        + b_wobble * np.cos(np.radians(servo_deg))
    )


def build_angles(optical_angles: list, retardances: list) -> list:
    """Build (theta, delta) pairs for RETARDER-type system_matrix.

    Args:
        optical_angles: Fast-axis angles in degrees, one per servo.
        retardances: Retardance in radians, one per servo.

    Returns:
        List of (theta_deg, delta_rad) tuples.
    """
    return list(zip(optical_angles, retardances))
