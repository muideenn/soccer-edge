"""Time-weighted Dixon-Coles model with ridge shrinkage and a Laplace covariance.

log λ_home = μ + home + att[h] + def[a] + δ·tier2
log λ_away = μ        + att[a] + def[h] + δ·tier2

Fitting a country's first and second divisions together lets promoted clubs carry
information from the division below (the level gap is identified through clubs that
moved between divisions). Fitted by Newton's method on the penalised weighted Poisson
likelihood; ρ (low-score correlation) is fitted afterwards by 1-D maximisation.
"""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson


def tau(x, y, lh, la, rho):
    t = np.ones(np.broadcast(x, y, lh).shape)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


class DixonColes:
    def __init__(self, xi=0.0019, l2=2.0, max_goals=10):
        self.xi, self.l2, self.G = xi, l2, max_goals
        self.theta, self.teams = None, None

    def _design(self, h, a, tier2, n):
        N = len(h)
        P = 3 + 2 * n
        X = np.zeros((2 * N, P))
        r = np.arange(N)
        X[:, 0] = 1
        X[r, 1] = 1                       # home advantage on home-goal rows
        X[:N, 2] = tier2
        X[N:, 2] = tier2
        X[r, 3 + h] = 1                   # home attack
        X[r, 3 + n + a] = 1               # away defence
        X[N + r, 3 + a] = 1               # away attack
        X[N + r, 3 + n + h] = 1           # home defence
        return X

    def fit(self, df, ref_date, neutral=None):
        """df: past matches with columns home, away, hg, ag, date, tier."""
        days = (ref_date - df.date).dt.days.values.astype(float)
        w = np.exp(-self.xi * days)
        teams = sorted(set(df.home) | set(df.away))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        h = df.home.map(idx).values
        a = df.away.map(idx).values
        t2 = (df.tier.values == 2).astype(float)
        X = self._design(h, a, t2, n)
        if neutral is not None:
            X[: len(h), 1] = 1 - neutral.astype(float)
        y = np.concatenate([df.hg.values, df.ag.values]).astype(float)
        ww = np.concatenate([w, w])
        pen = np.r_[1e-6, 1e-6, 1e-6, np.full(2 * n, self.l2)]
        theta = np.zeros(X.shape[1])
        theta[0] = np.log(max(y.mean(), 0.1))
        if self.theta is not None and self.teams is not None:  # warm start
            old = {t: i for i, t in enumerate(self.teams)}
            no = len(self.teams)
            theta[:3] = self.theta[:3]
            for t, i in idx.items():
                if t in old:
                    theta[3 + i] = self.theta[3 + old[t]]
                    theta[3 + n + i] = self.theta[3 + no + old[t]]
        for _ in range(30):
            eta = X @ theta
            mu = np.exp(eta)
            g = X.T @ (ww * (y - mu)) - pen * theta
            H = (X * (ww * mu)[:, None]).T @ X + np.diag(pen)
            step = np.linalg.solve(H, g)
            theta += step
            if np.max(np.abs(step)) < 1e-7:
                break
        eta = X @ theta
        mu = np.exp(eta)
        H = (X * (ww * mu)[:, None]).T @ X + np.diag(pen)
        self.cov = np.linalg.inv(H)
        self.theta, self.teams, self.idx, self.n = theta, teams, idx, n
        N = len(h)
        lh, la = mu[:N], mu[N:]
        x, yy = df.hg.values, df.ag.values
        low = (x <= 1) & (yy <= 1)

        def nll(rho):
            t = tau(x[low], yy[low], lh[low], la[low], rho)
            if np.any(t <= 0):
                return 1e9
            return -np.sum(w[low] * np.log(t))

        self.rho = minimize_scalar(nll, bounds=(-0.25, 0.25), method="bounded").x
        self.n_train = len(df)
        return self

    def linear_predictor(self, home, away, tier2=0.0, neutral=False):
        """Return (eta_h, eta_a) and their 2x2 covariance; None if a team is unseen."""
        if home not in self.idx or away not in self.idx:
            return None
        n = self.n
        gh = np.zeros(len(self.theta))
        ga = np.zeros(len(self.theta))
        gh[0] = ga[0] = 1
        gh[1] = 0 if neutral else 1
        gh[2] = ga[2] = tier2
        hi, ai = self.idx[home], self.idx[away]
        gh[3 + hi] = 1
        gh[3 + n + ai] = 1
        ga[3 + ai] = 1
        ga[3 + n + hi] = 1
        Gm = np.vstack([gh, ga])
        return Gm @ self.theta, Gm @ self.cov @ Gm.T

    def score_matrix(self, lh, la, rho=None):
        return score_matrix(lh, la, self.rho if rho is None else rho, self.G)


def score_matrix(lh, la, rho, G=10):
    """Vectorised DC score matrix. lh, la: arrays of shape S -> output S + (G+1, G+1)."""
    lh = np.asarray(lh, float)[..., None, None]
    la = np.asarray(la, float)[..., None, None]
    g = np.arange(G + 1)
    x = g[:, None]
    y = g[None, :]
    M = poisson.pmf(x, lh) * poisson.pmf(y, la) * tau(x, y, lh, la, rho)
    M = np.clip(M, 0, None)
    return M / M.sum(axis=(-1, -2), keepdims=True)


def sample_matrices(eta, cov, rho, n_draws, rng, G=10):
    """Parameter-uncertainty Monte Carlo: draw (eta_h, eta_a) ~ N(eta, cov) -> score matrices."""
    L = np.linalg.cholesky(cov + 1e-12 * np.eye(2))
    z = rng.standard_normal((n_draws, 2)) @ L.T + eta
    lam = np.exp(z)
    return score_matrix(lam[:, 0], lam[:, 1], rho, G), lam
