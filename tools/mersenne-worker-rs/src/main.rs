mod quantum_resonance_kernel;
mod sieve;

use malachite::natural::Natural;
use malachite::num::arithmetic::traits::{ModPow, Pow};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::time::{Instant, SystemTime};
use clap::Parser;
use indicatif::{ProgressBar, ProgressStyle};
use quantum_resonance_kernel::QuantumResonanceKernel;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    #[arg(short, long)]
    block_id: i32,

    #[arg(short, long)]
    p_start: u32,

    #[arg(short, long)]
    p_end: u32,

    #[arg(short, long, default_value = "ALPHA-QUANTUM")]
    probe: String,

    #[arg(short, long, default_value = "results/mersenne/domino_wave/")]
    out: String,

    #[arg(short, long, default_value_t = 0.85)]
    threshold: f64,

    #[arg(short, long, default_value = "hybrid")]
    method: String, // hybrid, spectral, ll
}

#[derive(Serialize, Deserialize, Debug)]
struct BlockResult {
    block_id: i32,
    probe: String,
    p_start: u32,
    p_end: u32,
    candidates_sieved: usize,
    fad_rejected: usize,
    spectral_anomalies: usize,
    primes_found: Vec<u32>,
    wall_time_s: f64,
    timestamp: String,
}

#[derive(Serialize, Deserialize, Debug)]
struct TelemetryEvent {
    p: u32,
    action: String,
    spectral_score: f64,
    wall_time_ms: u64,
}

/// Sieve of Eratosthenes para pre-filtrar candidatos pequeños.
fn sieve_primes(lo: u32, hi: u32) -> Vec<u32> {
    if hi < 2 { return vec![]; }
    let mut primes = Vec::new();
    let mut is_prime = vec![true; (hi - lo + 1) as usize];
    
    let limit = (hi as f64).sqrt() as u32;
    for p in 2..=limit {
        let mut start = ((lo + p - 1) / p) * p;
        if start < p * p { start = p * p; }
        for j in (start..=hi).step_by(p as usize) {
            is_prime[(j - lo) as usize] = false;
        }
    }
    
    for i in 0..is_prime.len() {
        let p = lo + i as u32;
        if is_prime[i] && p >= 2 {
            primes.push(p);
        }
    }
    primes
}

/// Test de Lucas-Lehmer optimizado con Malachite (FFT-based multiplication).
fn lucas_lehmer(p: u32) -> bool {
    if p == 2 { return true; }
    if p == 3 { return true; }
    
    // M = 2^p - 1
    let m = (Natural::from(2u32)).pow(p as u64) - Natural::from(1u32);
    let mut s = Natural::from(4u32);
    
    for _ in 0..p - 2 {
        // s = (s^2 - 2) mod M
        let s_sq = &s * &s;
        let s_sq_minus_2 = s_sq - Natural::from(2u32);
        
        // Fast Mersenne Modulo: x mod (2^p - 1)
        let low = &s_sq_minus_2 & &m;
        let high = &s_sq_minus_2 >> (p as u64);
        s = low + high;
        
        if s >= m {
            s -= &m;
        }
    }
    
    s == Natural::from(0u32)
}

fn main() {
    let args = Args::parse();
    let out_dir = PathBuf::from(&args.out);
    std::fs::create_dir_all(&out_dir).expect("Failed to create output directory");

    println!("[Block {}] Gahenax Interceptor v3.0 (Hyper-Scale Mode)", args.block_id);
    println!("  Rango: p=[{}, {}] | Threshold: {}", args.p_start, args.p_end, args.threshold);
    
    let start_time = Instant::now();
    
    // Fase 1: Sieve Clásico
    let candidates = sieve_primes(args.p_start, args.p_end);
    let n_sieved = candidates.len();
    println!("  Candidatos post-sieve Eratóstenes: {}", n_sieved);

    // Fase 1.5: Filtro Algebraico Determinista (FAD)
    let mut fad_rejected = 0;
    let mut fad_survivors = Vec::new();
    let max_k = 50_000; // Evaluará divisores modulares hasta la cota predefinida térmica.
    
    for &p in &candidates {
        if sieve::pass_fad_filter(p, max_k) {
            fad_survivors.push(p);
        } else {
            fad_rejected += 1;
        }
    }
    
    let n_evaluations = fad_survivors.len();
    println!("  Candidatos post-FAD (Recall 1.0): {} (Rechazados algebraicamente: {})", n_evaluations, fad_rejected);

    // Fase 2: Quantum Resonance Filter (Ghost Locus)
    let q_kernel = QuantumResonanceKernel::new(16);
    let pb = ProgressBar::new(n_evaluations as u64);
    pb.set_style(ProgressStyle::default_bar()
        .template("{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({eta}) LL-Tests: {msg}")
        .unwrap()
        .progress_chars("#>-"));

    let results: Vec<(u32, bool, f64, u64)> = fad_survivors.par_iter().map(|&p| {
        let t0 = Instant::now();
        let score = q_kernel.calculate_score(p as u64);
        
        let is_prime = match args.method.to_lowercase().as_str() {
            "spectral" => false, 
            "ll" => lucas_lehmer(p),
            "hybrid" | _ => {
                if score >= args.threshold {
                    lucas_lehmer(p)
                } else {
                    false
                }
            }
        };
        
        let elapsed = t0.elapsed().as_millis() as u64;
        pb.inc(1);
        (p, is_prime, score, elapsed)
    }).collect();

    pb.finish_with_message("Búsqueda completada");

    let mut primes_found = Vec::new();
    let mut telemetry = Vec::new();
    let mut spectral_anomalies = 0;

    for (p, is_prime, score, ms) in results {
        let action = if is_prime {
            primes_found.push(p);
            "PRIME".to_string()
        } else if score >= args.threshold {
            spectral_anomalies += 1;
            "ANOMALY_COMPOSITE".to_string()
        } else {
            "SPECTRAL_LOW_PRIORITY".to_string()
        };
        
        telemetry.push(TelemetryEvent { 
            p, 
            action, 
            spectral_score: score, 
            wall_time_ms: ms 
        });
    }

    let wall_time = start_time.elapsed().as_secs_f64();
    let timestamp = format!("{:?}", SystemTime::now());

    let final_result = BlockResult {
        block_id: args.block_id,
        probe: args.probe,
        p_start: args.p_start,
        p_end: args.p_end,
        candidates_sieved: n_sieved,
        fad_rejected,
        spectral_anomalies,
        primes_found: primes_found.clone(),
        wall_time_s: wall_time,
        timestamp,
    };

    // Guardar resultados
    let result_path = out_dir.join(format!("block_result_{}.json", args.block_id));
    let mut file = File::create(result_path).expect("Failed to create result file");
    file.write_all(serde_json::to_string_pretty(&final_result).unwrap().as_bytes()).unwrap();

    let tele_path = out_dir.join(format!("block_telemetry_{}.jsonl", args.block_id));
    let mut t_file = File::create(tele_path).expect("Failed to create telemetry file");
    for event in telemetry {
        t_file.write_all(format!("{}\n", serde_json::to_string(&event).unwrap()).as_bytes()).unwrap();
    }

    println!("\n[Block {}] Finalizado en {:.2}s.", args.block_id, wall_time);
    println!("  Anomalías Cuánticas: {}", spectral_anomalies);
    println!("  Primos Confirmados: {:?}", primes_found);
}
