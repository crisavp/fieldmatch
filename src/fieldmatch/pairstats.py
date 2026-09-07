"""Validation statistics and an optional scatter for collocated pairs.

Directions are handled as circular quantities throughout: a model at 10 deg
against an observation at 350 deg is a 20 deg error, not 340. Means are
vector means and errors are wrapped to [-180, 180); scatter index and
regression slope are meaningless on an angle and are reported as NaN.
"""
import numpy as np

from .quantities import DIRECTION_VARS


def _wrap180(d):
    return (np.asarray(d) + 180.0) % 360.0 - 180.0


def _circmean(a):
    r = np.deg2rad(a)
    return float(np.degrees(np.arctan2(np.mean(np.sin(r)), np.mean(np.cos(r)))) % 360.0)


def pair_stats(obs, mod, circular=False):
    """Standard marine-verification stats for one obs/model variable pair."""
    m = np.isfinite(obs) & np.isfinite(mod)
    o, p = np.asarray(obs)[m], np.asarray(mod)[m]
    n = o.size
    if n == 0:
        return {"n": 0}
    if circular:
        err = _wrap180(p - o)
        return {"n": n, "obs_mean": _circmean(o), "mod_mean": _circmean(p),
                "bias": float(np.mean(err)),
                "rmse": float(np.sqrt(np.mean(err ** 2))),
                "si": np.nan, "corr": np.nan, "ols_origin_slope": np.nan,
                "circular": True}
    bias = float(np.mean(p - o))
    rmse = float(np.sqrt(np.mean((p - o) ** 2)))
    si = float(np.sqrt(np.mean(((p - np.mean(p)) - (o - np.mean(o))) ** 2))
               / np.mean(o)) if np.mean(o) else np.nan
    corr = (float(np.corrcoef(o, p)[0, 1])
            if n > 1 and np.std(o) > 0 and np.std(p) > 0 else np.nan)
    slope = float(np.sum(o * p) / np.sum(o * o)) if np.sum(o * o) else np.nan
    return {"n": n, "obs_mean": float(np.mean(o)), "mod_mean": float(np.mean(p)),
            "bias": bias, "rmse": rmse, "si": si, "corr": corr,
            "ols_origin_slope": slope, "circular": False}


def stats_table(ds, variables=None):
    """{var: stats} for every obs var with a model_<var> partner."""
    if variables is None:
        variables = ([ds.attrs["variable"]] if "variable" in ds.attrs else
                     [v for v in ds.data_vars if f"model_{v}" in ds.data_vars
                      and ds[v].dtype.kind in "fiu"])
    return {v: pair_stats(ds[v].values, ds[f"model_{v}"].values,
                          circular=v in DIRECTION_VARS)
            for v in variables}


def format_stats(table):
    hdr = f"{'var':12} {'n':>7} {'obs':>7} {'mod':>7} {'bias':>7} {'rmse':>7} {'SI':>6} {'corr':>6} {'OLS0':>6}"
    lines = [hdr, "-" * len(hdr)]
    for v, s in table.items():
        if s["n"] == 0:
            lines.append(f"{v:12} {0:>7d}   (no valid pairs)")
            continue
        tail = ("     -      -      -   (circular)" if s.get("circular")
                else f"{s['si']:>6.3f} {s['corr']:>6.3f} {s['ols_origin_slope']:>6.3f}")
        lines.append(f"{v:12} {s['n']:>7d} {s['obs_mean']:>7.2f} {s['mod_mean']:>7.2f} "
                     f"{s['bias']:>7.2f} {s['rmse']:>7.2f} {tail}")
    return "\n".join(lines)


def plot_scatter(ds, var, out_png, title=""):
    """Write the sole supported plot: an observation/model scatter."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    o, p = ds[var].values, ds[f"model_{var}"].values
    m = np.isfinite(o) & np.isfinite(p)
    o, p = o[m], p[m]
    circular = var in DIRECTION_VARS
    fig, ax = plt.subplots(figsize=(6, 6))

    if o.size == 0:
        ax.text(0.5, 0.5, "No valid obs/model pairs", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        fig.suptitle(title or var)
        fig.tight_layout()
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
        return

    s = pair_stats(o, p, circular=circular)
    if circular:
        lo, hi = 0.0, 360.0
    else:
        lo, hi = float(min(o.min(), p.min())), float(max(o.max(), p.max()))
        pad = (hi - lo) * 0.05 or max(abs(lo) * 0.05, 1.0)
        lo, hi = lo - pad, hi + pad
    ax.hexbin(o, p, gridsize=40, mincnt=1, cmap="viridis", extent=(lo, hi, lo, hi))
    ax.plot([lo, hi], [lo, hi], "k--", lw=1)
    metrics = f"n={s['n']}  bias={s['bias']:.2f}  rmse={s['rmse']:.2f}"
    if not circular:
        metrics += f"  SI={s['si']:.3f}  r={s['corr']:.3f}"
    ax.set(xlabel=f"observed {var}", ylabel=f"model {var}",
           xlim=(lo, hi), ylim=(lo, hi), title="\n".join(filter(None, (title, metrics))))
    ax.set_aspect("equal")

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
