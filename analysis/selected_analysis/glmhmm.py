# Vendored unchanged from perceptual-decision-making/scripts/ so this directory stands alone.
"""Gaussian input-driven GLM-HMM (self-contained, numpy/scipy only).

This is the continuous-emission analog of the Bernoulli GLM-HMM in Ashwood et al.
2021. Each latent state k has its own Gaussian GLM emission:

    y_t | z_t = k  ~  Normal(w_k . x_t,  sigma_k^2)

with a K x K first-order Markov transition matrix A and initial distribution pi.
Because the emission is Gaussian, every EM update is closed form:

  * E-step: forward-backward in log space -> gamma (state posteriors) and
    xi (transition posteriors).
  * M-step: pi and A via (Dirichlet-MAP) counts (paper Eq. 15-16); per-state
    (w_k, sigma_k^2) via weighted least squares (replaces the Bernoulli BFGS step).

Priors (MAP, matching the paper's structure): Gaussian(0, sigma_w^2) on weights,
Dirichlet(alpha) on transition rows. Fitting supports multiple sequences (one per
trial-block / fly) and multiple random restarts.

The API mirrors the subset of ssm's GLM-HMM that the analysis needs:
    m = GaussianGLMHMM(K, M); m.fit(datas, inputs); m.log_likelihood(datas, inputs)
    z = m.most_likely_states(y, x); ll = m.expected_states(y, x)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.special import logsumexp

_LOG2PI = np.log(2.0 * np.pi)


def _normal_logpdf(y, mean, var):
    """Elementwise log N(y | mean, var)."""
    return -0.5 * (_LOG2PI + np.log(var) + (y - mean) ** 2 / var)


@dataclass
class GaussianGLMHMM:
    K: int                      # number of latent states
    M: int                      # number of input covariates (design-matrix width)
    sigma_w: float = 2.0        # std of Gaussian prior on GLM weights (MAP regularization)
    alpha: float = 1.0          # Dirichlet concentration on transition rows (>=1)
    min_var: float = 1e-3       # floor on emission variance for stability
    seed: int = 0

    W: np.ndarray = field(default=None, repr=False)   # (K, M) emission weights
    var: np.ndarray = field(default=None, repr=False)  # (K,) emission variances
    log_A: np.ndarray = field(default=None, repr=False)  # (K, K) log transition
    log_pi: np.ndarray = field(default=None, repr=False)  # (K,) log initial

    # -- initialization ---------------------------------------------------
    def _init_params(self, datas, inputs, rng):
        ys = np.concatenate(datas)
        Xs = np.concatenate(inputs)
        # global least-squares fit, then perturb per state so states are distinct
        w0, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
        resid = ys - Xs @ w0
        v0 = max(float(resid.var()), self.min_var)
        self.W = np.array([w0 + rng.normal(0, 0.5 * (abs(w0) + 1.0)) for _ in range(self.K)])
        self.var = np.full(self.K, v0)
        # sticky-ish transitions + flat-ish initial
        A = np.full((self.K, self.K), 1.0) + np.eye(self.K) * (5.0 * self.K)
        A += rng.random((self.K, self.K)) * 0.1
        A /= A.sum(1, keepdims=True)
        self.log_A = np.log(A)
        self.log_pi = np.log(np.full(self.K, 1.0 / self.K))

    # -- emission log-likelihoods ----------------------------------------
    def _log_likes(self, y, X, mask=None):
        """(T, K) log p(y_t | z_t=k, x_t). Masked (test) rows contribute 0.

        Setting the emission loglike to 0 at masked positions makes the forward-
        backward marginalize over the latent state there without conditioning on the
        observation -- so a train-only fit ignores held-out points, and the held-out
        predictive LL is full-sequence LL minus train-only LL.
        """
        mean = X @ self.W.T                # (T, K)
        ll = _normal_logpdf(y[:, None], mean, self.var[None, :])
        if mask is not None:
            ll = ll * mask[:, None]        # mask: 1 observed, 0 held-out
        return ll

    # -- forward-backward -------------------------------------------------
    @staticmethod
    def _lse_axis0(mat):
        """Fast logsumexp over axis 0 of a (K, K) matrix -> (K,)."""
        m = mat.max(axis=0)
        return m + np.log(np.exp(mat - m).sum(axis=0))

    @staticmethod
    def _lse_axis1(mat):
        m = mat.max(axis=1)
        return m + np.log(np.exp(mat - m[:, None]).sum(axis=1))

    def _forward_backward(self, log_likes):
        T, K = log_likes.shape
        log_A = self.log_A
        log_alpha = np.empty((T, K))
        log_beta = np.empty((T, K))
        log_alpha[0] = self.log_pi + log_likes[0]
        for t in range(1, T):
            log_alpha[t] = log_likes[t] + self._lse_axis0(log_alpha[t - 1][:, None] + log_A)
        log_beta[T - 1] = 0.0
        for t in range(T - 2, -1, -1):
            log_beta[t] = self._lse_axis1(
                log_A + (log_likes[t + 1] + log_beta[t + 1])[None, :])
        m = log_alpha[-1].max()
        ll = m + np.log(np.exp(log_alpha[-1] - m).sum())
        log_gamma = log_alpha + log_beta - ll
        # xi summed over t: (K, K)
        log_xi_sum = None
        if T > 1:
            terms = (log_alpha[:-1, :, None] + self.log_A[None, :, :]
                     + (log_likes[1:] + log_beta[1:])[:, None, :] - ll)
            log_xi_sum = logsumexp(terms, axis=0)
        return log_gamma, log_xi_sum, ll

    # -- EM ---------------------------------------------------------------
    def _e_step(self, datas, inputs, masks=None):
        gammas, xi_sums, total_ll = [], [], 0.0
        masks = masks or [None] * len(datas)
        for y, X, mk in zip(datas, inputs, masks):
            log_likes = self._log_likes(y, X, mk)
            log_gamma, log_xi_sum, ll = self._forward_backward(log_likes)
            gammas.append(np.exp(log_gamma))
            xi_sums.append(np.exp(log_xi_sum) if log_xi_sum is not None
                           else np.zeros((self.K, self.K)))
            total_ll += ll
        return gammas, xi_sums, total_ll

    def _m_step(self, datas, inputs, gammas, xi_sums, masks=None):
        K, M = self.K, self.M
        # initial distribution (with flat Dirichlet -> just normalized first-step gamma)
        pi = np.sum([g[0] for g in gammas], axis=0)
        pi = pi / pi.sum()
        self.log_pi = np.log(pi + 1e-16)

        # transition matrix, Dirichlet(alpha) MAP (paper Eq. 16)
        xi = np.sum(xi_sums, axis=0)                    # (K, K)
        A = (self.alpha - 1.0) + xi
        A = A / A.sum(1, keepdims=True)
        self.log_A = np.log(A + 1e-16)

        # emissions: weighted ridge regression per state (Gaussian-prior MAP)
        Xall = np.concatenate(inputs)                   # (N, M)
        yall = np.concatenate(datas)                    # (N,)
        gall = np.concatenate(gammas)                   # (N, K)
        if masks is not None:
            mk = np.concatenate([np.asarray(m, float) for m in masks])
            gall = gall * mk[:, None]                   # exclude held-out from emission fit
        ridge = (1.0 / self.sigma_w ** 2)
        for k in range(K):
            wgt = gall[:, k]                            # (N,)
            XtW = Xall.T * wgt                          # (M, N)
            A_mat = XtW @ Xall + ridge * self.var[k] * np.eye(M)
            b = XtW @ yall
            self.W[k] = np.linalg.solve(A_mat, b)
            resid = yall - Xall @ self.W[k]
            wsum = wgt.sum()
            self.var[k] = max(float((wgt * resid ** 2).sum() / max(wsum, 1e-8)),
                              self.min_var)

    def _fit_once(self, datas, inputs, rng, max_iter, tol, masks=None):
        self._init_params(datas, inputs, rng)
        prev = -np.inf
        lls = []
        for _ in range(max_iter):
            gammas, xi_sums, ll = self._e_step(datas, inputs, masks)
            lls.append(ll)
            self._m_step(datas, inputs, gammas, xi_sums, masks)
            if ll - prev < tol and _ > 2:
                break
            prev = ll
        # final ll after last m-step
        _, _, ll = self._e_step(datas, inputs, masks)
        return ll, lls

    def fit(self, datas, inputs, n_restarts=10, max_iter=200, tol=1e-4, verbose=False,
            masks=None):
        """Fit with `n_restarts` random inits; keep the best-LL solution.

        datas: list of 1D arrays (observations per sequence).
        inputs: list of 2D arrays (T, M) design matrices per sequence.
        masks: optional list of 1D arrays (1 observed / 0 held-out) per sequence; held-out
            observations are excluded from state inference and the emission fit.
        """
        datas = [np.asarray(y, float) for y in datas]
        inputs = [np.asarray(X, float) for X in inputs]
        best = None
        for r in range(n_restarts):
            rng = np.random.default_rng(self.seed + r)
            try:
                ll, _ = self._fit_once(datas, inputs, rng, max_iter, tol, masks)
            except np.linalg.LinAlgError:
                continue
            if verbose:
                print(f"    restart {r}: ll={ll:.2f}")
            snap = (self.W.copy(), self.var.copy(), self.log_A.copy(), self.log_pi.copy())
            if best is None or ll > best[0]:
                best = (ll, snap)
        if best is None:
            raise RuntimeError("all restarts failed")
        self.W, self.var, self.log_A, self.log_pi = best[1]
        return best[0]

    # -- inference / scoring ---------------------------------------------
    def log_likelihood(self, datas, inputs):
        total = 0.0
        for y, X in zip(datas, inputs):
            _, _, ll = self._forward_backward(self._log_likes(np.asarray(y, float),
                                                              np.asarray(X, float)))
            total += ll
        return total

    def held_out_ll(self, datas, inputs, masks):
        """Held-out predictive LL and predicted means at masked (test) positions.

        For each sequence: test_ll = logp(all y) - logp(y_train), where y_train uses the
        mask (held-out emissions set to 0). Returns (total_test_ll, y_true, y_pred) with
        the latter two concatenated over held-out positions for R^2/MSE scoring.
        """
        total = 0.0
        y_true, y_pred = [], []
        for y, X, mk in zip(datas, inputs, masks):
            y = np.asarray(y, float); X = np.asarray(X, float); mk = np.asarray(mk, float)
            _, _, ll_all = self._forward_backward(self._log_likes(y, X))
            log_gamma, _, ll_tr = self._forward_backward(self._log_likes(y, X, mk))
            total += (ll_all - ll_tr)
            test_idx = np.where(mk == 0)[0]
            if test_idx.size:
                gamma = np.exp(log_gamma[test_idx])          # (n_test, K)
                means = X[test_idx] @ self.W.T               # (n_test, K)
                y_pred.append(np.einsum("tk,tk->t", gamma, means))
                y_true.append(y[test_idx])
        yt = np.concatenate(y_true) if y_true else np.array([])
        yp = np.concatenate(y_pred) if y_pred else np.array([])
        return total, yt, yp

    def causal_ll_and_pred(self, y, X):
        """Causal (filter-only) sequence LL and one-step-ahead predicted means.

        At each t the predicted state belief p(z_t | y_<t) and prediction of y_t use ONLY
        past observations -- no future leakage -- so this is the honest forward-prediction
        score. The returned LL equals log p(y_1:T) (chain rule); preds are E[y_t | y_<t].
        """
        y = np.asarray(y, float); X = np.asarray(X, float)
        log_likes = self._log_likes(y, X)
        T, K = log_likes.shape
        log_pred = self.log_pi.copy()          # p(z_0) ; then p(z_t | y_<t)
        ll = 0.0
        preds = np.empty(T)
        for t in range(T):
            m = log_pred.max()
            pb = np.exp(log_pred - m); pb /= pb.sum()   # predicted belief given past
            preds[t] = float(pb @ (X[t] @ self.W.T))    # E[y_t | y_<t]
            log_joint = log_pred + log_likes[t]
            c = logsumexp(log_joint)                    # log p(y_t | y_<t)
            ll += c
            log_filt = log_joint - c                    # p(z_t | y_<=t)
            log_pred = self._lse_axis0(log_filt[:, None] + self.log_A)  # p(z_{t+1} | y_<=t)
        return ll, preds

    def expected_states(self, y, X):
        log_gamma, _, _ = self._forward_backward(
            self._log_likes(np.asarray(y, float), np.asarray(X, float)))
        return np.exp(log_gamma)

    def most_likely_states(self, y, X):
        """Viterbi path."""
        log_likes = self._log_likes(np.asarray(y, float), np.asarray(X, float))
        T, K = log_likes.shape
        delta = np.empty((T, K)); psi = np.empty((T, K), int)
        delta[0] = self.log_pi + log_likes[0]
        for t in range(1, T):
            scores = delta[t - 1][:, None] + self.log_A
            psi[t] = np.argmax(scores, axis=0)
            delta[t] = log_likes[t] + np.max(scores, axis=0)
        z = np.empty(T, int); z[-1] = int(np.argmax(delta[-1]))
        for t in range(T - 2, -1, -1):
            z[t] = psi[t + 1, z[t + 1]]
        return z

    @property
    def transition_matrix(self):
        return np.exp(self.log_A)

    def expected_dwell(self):
        """Expected dwell time per state (in # observations) from diag(A)."""
        p = np.diag(self.transition_matrix)
        return 1.0 / (1.0 - np.clip(p, 0, 1 - 1e-9))

    def sample(self, T, X, rng=None):
        """Generate (z, y) given design matrix X (T, M). For recovery tests."""
        rng = rng or np.random.default_rng(0)
        A = self.transition_matrix
        z = np.empty(T, int)
        z[0] = rng.choice(self.K, p=np.exp(self.log_pi))
        for t in range(1, T):
            z[t] = rng.choice(self.K, p=A[z[t - 1]])
        mean = np.einsum("tm,tm->t", X, self.W[z])
        y = mean + rng.normal(0, np.sqrt(self.var[z]))
        return z, y
