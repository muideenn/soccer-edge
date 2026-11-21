"""Static charts for the HTML report (reference palette: blue / orange / aqua, light surface)."""
import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams.update({"font.family": "serif", "font.serif": ["CMU Serif", "Latin Modern Roman", "Times New Roman", "DejaVu Serif"], "mathtext.fontset": "cm"})
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def equity(strategies, path):
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150, facecolor=SURFACE)
    _style(ax)
    for k, (label, st) in enumerate(strategies.items()):
        b = st["bets"].sort_values("date")
        if not len(b):
            continue
        cum = np.cumsum(b.profit.values)
        ax.plot(b.date.values, cum, color=SERIES[k], lw=2, label=f"{label.replace('_', ' ')} ({len(b)} bets, {cum[-1]:+.0f} units)")
        if abs(cum[-1]) >= 10:  # small end values sit on the zero line; the legend carries them
            ax.annotate(f"{cum[-1]:+.0f}", (b.date.values[-1], cum[-1]), xytext=(4, 0), textcoords="offset points",
                        color=INK, fontsize=9, va="center")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("cumulative profit (1-unit flat stakes)", color=INK2, fontsize=9)
    ax.set_title("Out-of-sample betting results, 2018-19 to 2025-26", color=INK, fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def calibration(cal, path):
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.2), dpi=150, facecolor=SURFACE, sharey=True)
    for ax, oc in zip(axes, "HDA"):
        _style(ax)
        ax.plot([0, 1], [0, 1], color=GRID, lw=1)
        for k, (m, lab) in enumerate((("dc", "Dixon-Coles"), ("ens", "Ensemble"), ("mkt", "Market"))):
            c = cal[(cal.model == m) & (cal.outcome == oc)]
            ax.plot(c.mean_pred, c.observed, "-o", color=SERIES[k], lw=2, ms=4, label=lab)
        ax.set_title({"H": "Home win", "D": "Draw", "A": "Away win"}[oc], color=INK, fontsize=10, loc="left")
        ax.set_xlabel("predicted", color=INK2, fontsize=9)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("observed frequency", color=INK2, fontsize=9)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
