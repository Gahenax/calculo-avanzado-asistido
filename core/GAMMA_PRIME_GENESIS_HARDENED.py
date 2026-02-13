#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GAMMA_PRIME_GENESIS_HARDENED.py
===============================
Demostración computacional (audit-ready) de que gamma (Euler-Mascheroni)
emerge de la estructura prima (vias tipo Mertens / von Mangoldt).

Metodos:
A) Mertens product (log-estable):
   e^{-gamma} = lim_{x->inf} [ ln(x) * prod_{p<=x} (1 - 1/p) ]
   => gamma ~ -ln( ln(x) * prod_{p<=x} (1 - 1/p) )

B) von Mangoldt (lenta/ruidosa):
   sum_{n<=x} Lambda(n)/n = ln(x) - gamma + o(1)
   => gamma ~ ln(x) - sum_{n<=x} Lambda(n)/n
   Implementacion eficiente: sum_p ln(p) * sum_{k>=1, p^k<=x} 1/p^k

Notas:
- La convergencia es lenta (especialmente B). Esto es esperado.
- Este script prioriza estabilidad numerica y fidelidad a las formulas.

Autor: GAHENAX Core
"""

import sys
import argparse
from typing import List, Tuple

try:
    from mpmath import mp
except ImportError:
    print("CRITICAL: Requiere 'mpmath' (pip install mpmath).")
    sys.exit(1)


# -------------------- CONFIG DEFAULTS --------------------
DEFAULT_DPS = 80
DEFAULT_N = 2_000_000


# -------------------- PRIMES (SIEVE) --------------------
def primes_upto(n: int) -> List[int]:
    """Criba de Eratostenes rapida (bytearray) para primos <= n."""
    if n < 2:
        return []
    sieve = bytearray(b"\x01") * (n + 1)
    sieve[0:2] = b"\x00\x00"
    for i in range(4, n + 1, 2):
        sieve[i] = 0
    r = int(n**0.5)
    p = 3
    while p <= r:
        if sieve[p]:
            step = p * 2
            start = p * p
            sieve[start:n + 1:step] = b"\x00" * (((n - start) // step) + 1)
        p += 2
    primes = [2]
    primes.extend([i for i in range(3, n + 1, 2) if sieve[i]])
    return primes


# -------------------- MERTENS (LOG-STABLE) --------------------
def mertens_gamma_estimate(N: int) -> Tuple[mp.mpf, mp.mpf, int]:
    """
    Estima gamma usando:
      gamma ~ -ln( ln(x) * prod_{p<=x} (1 - 1/p) )
    Implementacion: log_prod = sum log(1 - 1/p), luego:
      ln(x)*prod = ln(x) * exp(log_prod)
      gamma = -log( ln(x) * exp(log_prod) )
    """
    ps = primes_upto(N)
    if not ps:
        raise ValueError("N demasiado pequeno para primos.")

    x = ps[-1]
    log_prod = mp.mpf(0)

    for p in ps:
        pmp = mp.mpf(p)
        log_prod += mp.log(1 - mp.mpf(1) / pmp)

    mertens_term = mp.log(mp.mpf(x)) * mp.e**(log_prod)
    gamma_est = -mp.log(mertens_term)
    return gamma_est, mertens_term, x


# -------------------- VON MANGOLDT (EFFICIENT POWERS) --------------------
def von_mangoldt_gamma_estimate(N: int, checkpoints: int = 6) -> Tuple[mp.mpf, int]:
    """
    Estima gamma usando:
      gamma ~ ln(x) - sum_{n<=x} Lambda(n)/n
    Donde Lambda(n) = ln(p) si n=p^k.

    Implementacion eficiente:
      S(x) = sum_{p<=x} ln(p) * sum_{k>=1: p^k<=x} 1/p^k
    """
    ps = primes_upto(N)
    if not ps:
        raise ValueError("N demasiado pequeno para primos.")

    x = ps[-1]
    S = mp.mpf(0)

    total = len(ps)
    marks = set()
    for j in range(1, checkpoints + 1):
        marks.add(int(total * j / checkpoints) - 1)
    marks.add(total - 1)

    for i, p in enumerate(ps):
        pmp = mp.mpf(p)
        ln_p = mp.log(pmp)

        invp = mp.mpf(1) / pmp
        term = invp
        power = p
        while power <= x:
            S += ln_p * term
            power *= p
            term *= invp

        if i in marks:
            gamma_est = mp.log(mp.mpf(x)) - S
            print(f"  [Lambda] primos {i+1:>9}/{total}: gamma_est={mp.nstr(gamma_est, 18)}", flush=True)

    gamma_est = mp.log(mp.mpf(x)) - S
    return gamma_est, x


# -------------------- MAIN / CLI --------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--N", type=int, default=DEFAULT_N,
                    help="Limite superior N para primos (default: 2,000,000)")
    ap.add_argument("--dps", type=int, default=DEFAULT_DPS,
                    help="Precision decimal mpmath (default: 80)")
    ap.add_argument("--method", type=str, default="both",
                    choices=["mertens", "mangoldt", "both"],
                    help="Metodo a ejecutar: mertens | mangoldt | both")
    args = ap.parse_args()

    mp.dps = args.dps
    gamma_ref = mp.euler

    print("\n--- GAMMA PRIME GENESIS (HARDENED) ---", flush=True)
    print(f"N={args.N}, dps={args.dps}, method={args.method}", flush=True)
    print(f"gamma_ref = {mp.nstr(gamma_ref, 30)}\n", flush=True)

    if args.method in ("mertens", "both"):
        print("[METODO A] Mertens product (log-estable)", flush=True)
        gamma_est, mertens_term, x = mertens_gamma_estimate(args.N)
        err = gamma_est - gamma_ref
        print(f"  x = p_max <= N = {x}", flush=True)
        print(f"  ln(x)*prod = {mp.nstr(mertens_term, 20)}", flush=True)
        print(f"  gamma_est  = {mp.nstr(gamma_est, 30)}", flush=True)
        print(f"  error      = {mp.nstr(err, 12)}   (abs={mp.nstr(abs(err), 8)})\n", flush=True)

    if args.method in ("mangoldt", "both"):
        print("[METODO B] von Mangoldt (lento/ruidoso, pero aritmetico puro)", flush=True)
        gamma_est, x = von_mangoldt_gamma_estimate(args.N)
        err = gamma_est - gamma_ref
        print(f"  x = p_max <= N = {x}", flush=True)
        print(f"  gamma_est  = {mp.nstr(gamma_est, 30)}", flush=True)
        print(f"  error      = {mp.nstr(err, 12)}   (abs={mp.nstr(abs(err), 8)})\n", flush=True)

    print("--- END ---\n", flush=True)


if __name__ == "__main__":
    main()
