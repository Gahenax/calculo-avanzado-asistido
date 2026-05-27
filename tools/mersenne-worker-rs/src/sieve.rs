/// Filtro Algebraico Determinista (FAD) 
/// Basado en el Teorema de Divisores de Mersenne.
/// Si q divide a M_p = 2^p - 1, entonces:
/// 1) q = 2kp + 1 (por consiguiente q = 1 mod p)
/// 2) q = +/- 1 mod 8
pub fn pass_fad_filter(p: u32, max_k: u32) -> bool {
    let p64 = p as u64;
    for k in 1..=max_k {
        let q = 2 * (k as u64) * p64 + 1;
        
        let rem = q % 8;
        if rem == 1 || rem == 7 {
            // Verificar si 2^p = 1 mod q
            if mod_pow_u64(2, p64, q) == 1 {
                // Se encontró un divisor q, por ende M_p es compuesto.
                return false; 
            }
        }
    }
    // No se halló divisor bajo la cota max_k; el candidato sobrevive.
    true
}

/// Exponenciación Modular rápida (evita uso costoso de BigInt)
#[inline(always)]
fn mod_pow_u64(mut base: u64, mut exp: u64, modulo: u64) -> u64 {
    let mut res = 1;
    base %= modulo;
    while exp > 0 {
        if exp % 2 == 1 {
            res = ((res as u128 * base as u128) % (modulo as u128)) as u64;
        }
        base = ((base as u128 * base as u128) % (modulo as u128)) as u64;
        exp /= 2;
    }
    res
}
