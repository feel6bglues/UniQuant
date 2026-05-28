# -*- coding: utf-8 -*-
import numpy as np
from typing import Tuple

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*dec_args, **dec_kwargs):
        return lambda f: f

@njit(cache=True, fastmath=True)
def _reduced_cost_numba(
    nonlinear: np.ndarray, t: np.ndarray, log_prices: np.ndarray
) -> float:
    """Reduced LPPL cost function using Variable Projection inside Numba."""
    tc = nonlinear[0]
    m = nonlinear[1]
    w = nonlinear[2]
    n = len(t)

    if tc <= t[n - 1] + 0.5:
        return 1e20

    s11 = 0.0
    s12 = 0.0
    s13 = 0.0
    s14 = 0.0
    s22 = 0.0
    s23 = 0.0
    s24 = 0.0
    s33 = 0.0
    s34 = 0.0
    s44 = 0.0
    r1 = 0.0
    r2 = 0.0
    r3 = 0.0
    r4 = 0.0
    yty = 0.0

    for i in range(n):
        tau = tc - t[i]
        if tau <= 0.0:
            return 1e20
        if tau < 1e-8:
            tau = 1e-8
        f = tau ** m
        log_tau = np.log(tau)
        g = f * np.cos(w * log_tau)
        h = f * np.sin(w * log_tau)
        y = log_prices[i]

        s11 += 1.0
        s12 += f
        s13 += g
        s14 += h
        s22 += f * f
        s23 += f * g
        s24 += f * h
        s33 += g * g
        s34 += g * h
        s44 += h * h
        r1 += y
        r2 += f * y
        r3 += g * y
        r4 += h * y
        yty += y * y

    A = np.empty((4, 4))
    A[0, 0] = s11
    A[0, 1] = s12
    A[0, 2] = s13
    A[0, 3] = s14
    A[1, 0] = s12
    A[1, 1] = s22
    A[1, 2] = s23
    A[1, 3] = s24
    A[2, 0] = s13
    A[2, 1] = s23
    A[2, 2] = s33
    A[2, 3] = s34
    A[3, 0] = s14
    A[3, 1] = s24
    A[3, 2] = s34
    A[3, 3] = s44
    rhs = np.array([r1, r2, r3, r4])

    try:
        beta = np.linalg.solve(A, rhs)
    except Exception:
        return 1e20

    sse = yty - (beta[0] * r1 + beta[1] * r2 + beta[2] * r3 + beta[3] * r4)
    if sse < 0.0:
        sse = 0.0
    return sse


@njit(cache=True, fastmath=True)
def _solve_linear_parameters_numba(
    t: np.ndarray, log_prices: np.ndarray, tc: float, m: float, w: float
) -> Tuple[float, float, float, float]:
    """JIT-compiled OLS solver using normal equations to obtain linear LPPL parameters."""
    n = len(t)
    s11 = 0.0
    s12 = 0.0
    s13 = 0.0
    s14 = 0.0
    s22 = 0.0
    s23 = 0.0
    s24 = 0.0
    s33 = 0.0
    s34 = 0.0
    s44 = 0.0
    r1 = 0.0
    r2 = 0.0
    r3 = 0.0
    r4 = 0.0

    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        f = tau ** m
        log_tau = np.log(tau)
        g = f * np.cos(w * log_tau)
        h = f * np.sin(w * log_tau)
        y = log_prices[i]

        s11 += 1.0
        s12 += f
        s13 += g
        s14 += h
        s22 += f * f
        s23 += f * g
        s24 += f * h
        s33 += g * g
        s34 += g * h
        s44 += h * h
        r1 += y
        r2 += f * y
        r3 += g * y
        r4 += h * y

    A = np.empty((4, 4))
    A[0, 0] = s11
    A[0, 1] = s12
    A[0, 2] = s13
    A[0, 3] = s14
    A[1, 0] = s12
    A[1, 1] = s22
    A[1, 2] = s23
    A[1, 3] = s24
    A[2, 0] = s13
    A[2, 1] = s23
    A[2, 2] = s33
    A[2, 3] = s34
    A[3, 0] = s14
    A[3, 1] = s24
    A[3, 2] = s34
    A[3, 3] = s44
    rhs = np.array([r1, r2, r3, r4])

    try:
        beta = np.linalg.solve(A, rhs)
        a, b, c1, c2 = beta[0], beta[1], beta[2], beta[3]
        c = np.sqrt(c1**2 + c2**2)
        phi = np.arctan2(-c2, c1)
        return a, b, c, phi
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


@njit(cache=True, fastmath=True)
def _de_solve_numba(
    t: np.ndarray,
    log_prices: np.ndarray,
    bounds: np.ndarray,
    popsize: int = 15,
    maxiter: int = 100,
    tol: float = 0.01,
    mutation_min: float = 0.5,
    mutation_max: float = 1.0,
    recombination: float = 0.7,
    seed: int = 42
) -> Tuple[np.ndarray, float, bool]:
    """
    Highly optimized, JIT-compiled Differential Evolution optimizer for LPPL fitting.
    Estimates non-linear params: [tc, m, w].
    """
    if seed >= 0:
        np.random.seed(seed)

    n_dim = 3
    pop_n = popsize * n_dim

    # Pop initialization
    pop = np.empty((pop_n, n_dim))
    for i in range(pop_n):
        for j in range(n_dim):
            pop[i, j] = bounds[j, 0] + np.random.rand() * (bounds[j, 1] - bounds[j, 0])

    # Compute initial fitness
    fitness = np.empty(pop_n)
    for i in range(pop_n):
        fitness[i] = _reduced_cost_numba(pop[i], t, log_prices)

    best_idx = np.argmin(fitness)
    best_fit = fitness[best_idx]
    best_sol = pop[best_idx].copy()

    # Iterate
    for it in range(maxiter):
        F = mutation_min + np.random.rand() * (mutation_max - mutation_min)

        for i in range(pop_n):
            # Select three distinct agents
            r1 = np.random.randint(0, pop_n)
            while r1 == i:
                r1 = np.random.randint(0, pop_n)
            r2 = np.random.randint(0, pop_n)
            while r2 == i or r2 == r1:
                r2 = np.random.randint(0, pop_n)
            r3 = np.random.randint(0, pop_n)
            while r3 == i or r3 == r1 or r3 == r2:
                r3 = np.random.randint(0, pop_n)

            # Mutation
            mutant = pop[r1] + F * (pop[r2] - pop[r3])

            # Bound correction (clipping)
            for j in range(n_dim):
                if mutant[j] < bounds[j, 0]:
                    mutant[j] = bounds[j, 0]
                elif mutant[j] > bounds[j, 1]:
                    mutant[j] = bounds[j, 1]

            # Crossover
            trial = pop[i].copy()
            j_rand = np.random.randint(0, n_dim)
            for j in range(n_dim):
                if np.random.rand() < recombination or j == j_rand:
                    trial[j] = mutant[j]

            # Evaluate
            trial_fit = _reduced_cost_numba(trial, t, log_prices)

            # Selection
            if trial_fit < fitness[i]:
                fitness[i] = trial_fit
                pop[i] = trial
                if trial_fit < best_fit:
                    best_fit = trial_fit
                    best_sol = trial.copy()

        # Convergence test
        fit_spread = np.max(fitness) - np.min(fitness)
        if fit_spread < tol:
            break

    # Success check
    success = best_fit < 1e18
    return best_sol, best_fit, success
