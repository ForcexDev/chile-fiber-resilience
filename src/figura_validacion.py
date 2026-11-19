"""Figura: PGA del modelo (Youngs 1997, suelo) frente a las 35 estaciones del ShakeMap del sismo."""
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from fallas import youngs_suelo

M, H = 8.8, 22.9
est = json.load(open("datos/externos/shakemap_stationlist.json"))["features"]
r_obs, pga_obs = [], []
for f in est:
    p = f["properties"]
    if p.get("station_type") != "seismic":
        continue
    amps = {a["name"]: a["value"] for c in p["channels"] for a in c["amplitudes"]}
    if "pga" in amps:
        r_obs.append(p["distances"]["rrup"])
        pga_obs.append(amps["pga"] / 100)
r = np.logspace(0.3, 3, 200)
ln, s = youngs_suelo(M, r, H)
res = np.log(pga_obs) - youngs_suelo(M, np.array(r_obs), H)[0]
print(f"estaciones: {len(r_obs)}, residuo medio {res.mean():.3f}, desv {res.std(ddof=1):.3f}")

plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b"})
fig, ax = plt.subplots(figsize=(7, 4.2))
ax.fill_between(r, np.exp(ln - s), np.exp(ln + s), color="#2a78d6", alpha=0.15, lw=0, label="modelo $\\pm\\sigma$")
ax.plot(r, np.exp(ln), color="#2a78d6", lw=2, label="modelo (mediana)")
ax.scatter(r_obs, pga_obs, s=36, color="#eb6834", edgecolor="white", linewidth=1, zorder=3,
           label=f"estaciones ShakeMap ({len(r_obs)})")
ax.axhline(0.215, color="#52514e", lw=1, ls="--")
ax.text(2.3, 0.235, "umbral de daño 0,215 g (intensidad VII)", color="#52514e", fontsize=9)
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(2, 1000); ax.set_ylim(0.005, 2)
ax.set_xlabel("Distancia a la ruptura $R_{rup}$ (km)")
ax.set_ylabel("PGA (g)")
ax.grid(True, which="major", color="#e4e3df", lw=0.6)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.legend(frameon=False, loc="lower left")
fig.tight_layout()
fig.savefig("validacion_pga.png", dpi=200)
