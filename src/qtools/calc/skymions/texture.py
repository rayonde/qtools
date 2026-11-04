#!/usr/bin/env python3
# Reconstructed skyrmion texture
# Justin, 2026-11-02
#
# Mostly following derivations from <Free-space topological optical textures: tutorial> [doi:10.1364/AOP.547634]
# and replicating results from <Topological robustness of classical and quantum optical skyrmions in atmospheric turbulence> [doi:10.1038/s41467-026-68751-3]
#
# Uses 'estimation.py' to generate a noisy Psi+ state (01+10) in the hybrid
# OAM + polarization basis (A in polarization, B in OAM), and then
# reconstruction of the density matrix using maximum-likelihood estimation.
# After which, tracing out the OAM to obtain the polarization density matrix
# to infer the Stokes vector at each spatial point, and calculating the charge Q.


import itertools

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import hsv_to_rgb

from estimation import rho_mle

# Assume basis {|H1>, |H0>, |V1>, |V0>} just like in [doi:10.1038/s41467-026-68751-3]
# Photon A in polarization basis, photon B in OAM basis
# rho_mle, rho = np.load("state.cache.npy")
rho4_mle = rho_mle.reshape((2, 2, 2, 2))
"""
Rewrite rho:
  ┌         ┐
  │ A B C D │  # |H1> for photon A (row)
  │ E F G H │  # |H0>
  │ I J K L │  # |V1>
  │ M N O P │  # |V0>
  └         ┘
as:
  ┌     ┐┌     ┐
  │ A E ││ B F │
  │ I M ││ J N │
  ╞     ╡╞     ╡
  │ C G ││ D H │
  │ K O ││ L P │
  └     ┘└     ┘
then:
  Pol B = rho[i]
  OAM B = rho[:, i]
  Pol A = rho[:, :, i]
  OAM B = rho[:, :, :, i]
"""

l0, l1 = 0, 1
N = 421
step = 20  # interval for printing arrows in plot

x = np.linspace(-3, 3, N)  # using nominal beam width w0 = 1
y = np.linspace(-3, 3, N)
X, Y = np.meshgrid(x, y)

R = (X**2 + Y**2) ** 0.5
P = np.arctan2(Y, X)

def lg0l(l, r, phi, w0=1):
    assert l == 0 or l == 1
    return np.sqrt(2 / np.pi * w0**2) \
        * np.exp(1j * l * phi) \
        * (np.sqrt(2) * r / w0) ** np.abs(l) \
        * np.exp(-r**2 / w0**2)

u0 = lg0l(l0, R, P)
u1 = lg0l(l1, R, P)
u = np.stack([u0, u1], axis=-1)  # NxN grid of [LG00, LG01]

# Trace out OAM to get 2x2 polarization density matrix
rho_A = np.zeros((N, N, 2, 2), dtype=complex)  # NxN grid of 2x2
for i, j in itertools.product(range(2), repeat=2):
    rho_A += (
        u[:, :, i, None, None].conj()
        * rho4_mle[:, i, :, j]  # 2x2 selection OAM_A = i, OAM_B = j
        * u[:, :, j, None, None]
    )

# Get Stokes vectors at each point
# Note that conventional Stokes is given by:
# - S0 = I = np.real(rho_A[:, :, 0, 0] + rho_A[:, :, 1, 1])
# - S3 = Q = np.real(rho_A[:, :, 0, 0] - rho_A[:, :, 1, 1])
# - S1 = U = 2 * np.real(rho_A[:, :,0, 1])
# - S2 = V = -2 * np.imag(rho_A[:, :,0, 1])
#
# Slightly different from the definitions Eqn 5-7 from [doi:10.1364/AOP.547634]
# - S0 = I
# - S1 = Q
# - S2 = U
# - S3 = -V
#
# We use a parameterization that yields the same skyrmion plot for [doi:10.1038/s41467-026-68751-3]
S0 = np.real(rho_A[:, :, 0, 0] + rho_A[:, :, 1, 1])
S3 = -(np.real(rho_A[:, :, 0, 0] - rho_A[:, :, 1, 1]))
S1 = 2 * np.real(rho_A[:, :,0, 1])
S2 = -2 * np.imag(rho_A[:, :,0, 1])
S = np.stack([S1, S2, S3], axis=-1) / S0[:, :, None]  # normalize intensity

# Extract normalized Stokes coefficients
dop = np.linalg.norm(S, axis=-1)  # degree of polarization
n = S / dop[:, :, None]  # normalized Stokes
valid = S0 > (1e-6 * np.max(S0))  # exclude points with -60dB intensities
n[~valid] = np.nan
nx, ny, nz = n[..., 0], n[..., 1], n[..., 2]

# Extract topological density and charge
dx = x[1] - x[0]
dy = y[1] - y[0]
dn_dy = np.gradient(n, y, axis=0)
dn_dx = np.gradient(n, x, axis=1)
density = 1 / (4 * np.pi) * np.sum(n * np.cross(dn_dx, dn_dy), axis=-1)
Q = np.nansum(density) * dx * dy  # Eqn 25, [doi:10.1364/AOP.547634]
print(f"\nSkyrmion number = {Q:.3f}")


### Plotting
# Simple HSV model
def cyl2color(z, phi):
    hue = phi / (2 * np.pi) + 0.5  # [-pi, pi] -> [0, 1]
    value = np.minimum(z, 0) + 1  # [-1, 0] -> [0, 1]
    saturation = 1 - np.maximum(z, 0)  # [0, 1] -> [1, 0]
    hsv = np.stack([hue, saturation, value], axis=-1)
    hsv[np.isnan(hsv)] = 0
    return hsv_to_rgb(hsv)

def s2color(sx, sy, sz):
    phi = np.arctan2(sy, sx)
    return cyl2color(sz, phi)


fig, ax = plt.subplots(figsize=(4, 4), layout="constrained")
# plt.pcolormesh(X, Y, sz, vmin=-1, vmax=1)

# Plot arrows
# https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.quiver.html
step = step
C = s2color(nx[::step, ::step], ny[::step, ::step], nz[::step, ::step])
plt.quiver(
    X[::step, ::step],
    Y[::step, ::step],
    nx[::step, ::step],
    ny[::step, ::step],
    pivot="mid",
    width=0.003,
    color=C.reshape(-1, 3),
)
plt.xlabel("$x$/$w_0$")
plt.ylabel("$y$/$w_0$")
plt.title(f"Skyrmion number, N = {Q:.3f}")

axin = ax.inset_axes([0.88, 0.07, 0.1, 0.1])
phis = np.linspace(-np.pi, np.pi, 101)
zs = np.linspace(-1, 1, 101)
X, Y = np.meshgrid(phis, zs)
Z = cyl2color(Y, X)
axin.pcolormesh(X, Y, Z)
# axin.set_ylabel("$S_z$", fontsize=5, labelpad=-5)
# axin.set_xlabel("$\\phi = \\tan^{-1}(S_y/S_x)$", fontsize=5, labelpad=-2)
axin.set_yticks([-1, 1], ["-1", "+1"])
axin.set_xticks([-np.pi, np.pi], ["$-\\pi$", "$\\pi$"])
axin.tick_params(axis='both', labelsize=6)
axin.invert_yaxis()

plt.savefig("skyrmion.png", dpi=250)
