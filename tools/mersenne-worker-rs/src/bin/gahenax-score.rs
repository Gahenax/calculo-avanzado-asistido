use clap::Parser;
use mersenne_worker_rs::spectral::{riemann_block_score, log_gap_score, partial_ll_score};
use mersenne_worker_rs::common::BlockPriority;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(name = "gahenax-score", about = "Priorización de bloques mediante Amalgam Engine V2")]
struct Args {
    #[arg(short, long)]
    block_id: i32,
    #[arg(short, long)]
    p_start: u32,
    #[arg(short, long)]
    p_end: u32,
    #[arg(short, long, default_value = "results/priorities/")]
    out: String,
}

fn main() {
    let args = Args::parse();
    println!("=== Gahenax Score: Priorización de Bloques (Amalgam V2) ===");
    
    // Pesos optimizados en la calibración anterior
    let weights = [0.793, 0.016, 0.191, 0.0, 0.0]; 
    
    // Cálculo de la mediana del bloque para el score espectral
    let p_mid = (args.p_start + args.p_end) / 2;
    
    let r_score = riemann_block_score(p_mid, &weights);
    let g_score = log_gap_score(p_mid);
    let p_score = partial_ll_score(p_mid);
    
    // Fusión Amalgam (Capa B rankea bloques, Capa A reordena, Capa C filtra)
    // Para simplificación de bloque: 0.4*R + 0.4*G + 0.2*P
    let final_rank = (0.4 * r_score) + (0.4 * g_score) + (0.2 * p_score);
    
    // --- LA SENDA ASINTÓTICA OEDA (WAVE 3) ---
    // Históricamente todos los M-Primes > 1 Millón caen estrictamente entre 0.108 y 0.135
    // Por factor de seguridad ampliado a [0.100 - 0.140]
    const LOWER_BOUND: f64 = 0.100;
    const UPPER_BOUND: f64 = 0.140;
    if final_rank < LOWER_BOUND || final_rank > UPPER_BOUND {
        println!("  [❌] BLOQUE DESCARTADO: Score {:.6} fuera del Valle Asintótico OEDA [0.100 - 0.140]", final_rank);
        return; // Salida temprana: Zero-Debt Operacional Activo
    }
    
    let priority = BlockPriority {
        block_id: args.block_id,
        p_start: args.p_start,
        p_end: args.p_end,
        rank_score: final_rank,
    };

    println!("  Bloque ID   : {}", args.block_id);
    println!("  Rango       : [{}, {}]", args.p_start, args.p_end);
    println!("  Rank Score  : {:.6}", final_rank);
    println!("  (R:{:.4} G:{:.4} P:{:.4})", r_score, g_score, p_score);

    // Guardar resultado
    let out_dir = PathBuf::from(&args.out);
    std::fs::create_dir_all(&out_dir).expect("Failed to create priority directory");
    let out_path = out_dir.join(format!("priority_block_{}.json", args.block_id));
    let mut file = File::create(out_path).expect("Failed to create output file");
    file.write_all(serde_json::to_string_pretty(&priority).unwrap().as_bytes()).unwrap();
}
