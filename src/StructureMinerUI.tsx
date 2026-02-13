import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Cpu, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { StructureScanner, math } from './core/StructureMiner';
import type { StructuralSignature } from './core/StructureMiner';
// @ts-ignore
import { BlockMath } from 'react-katex';

const StructureMinerUI: React.FC = () => {
    const [target, setTarget] = useState('1.61803398874989');
    const [isScanning, setIsScanning] = useState(false);
    const [progress, setProgress] = useState(0);
    const [result, setResult] = useState<StructuralSignature | null>(null);
    const [error, setError] = useState<string | null>(null);

    const startScan = async () => {
        setIsScanning(true);
        setResult(null);
        setError(null);
        setProgress(0);

        // Give UI a chance to render the loader
        await new Promise(resolve => setTimeout(resolve, 100));

        try {
            const scanner = new StructureScanner();
            const bnTarget = math.bignumber(target);

            // We run in a small timeout loop or just directly if it's fast enough
            // For 117k entries, it might take a few seconds
            const found = scanner.scan(bnTarget, (checked, total) => {
                setProgress(Math.round((checked / total) * 100));
            });

            if (found) {
                setResult(found);
            } else {
                setError('No se encontró una firma estructural estable en el espacio de búsqueda actual.');
            }
        } catch (err) {
            setError('Error en el formato del valor objetivo.');
        } finally {
            setIsScanning(false);
        }
    };

    const polyToLatex = (coeffs: number[], variable: string = 'n') => {
        const deg = coeffs.length - 1;
        let parts = [];
        for (let i = 0; i < coeffs.length; i++) {
            const c = coeffs[i];
            if (c === 0 && coeffs.length > 1) continue;
            const p = deg - i;
            let s = c.toString();
            if (p > 0) {
                if (c === 1) s = '';
                if (c === -1) s = '-';
                s += variable + (p > 1 ? `^{${p}}` : '');
            }
            parts.push(s);
        }
        return parts.join(' + ').replace(/\+ -/g, '- ');
    };

    return (
        <div className="glass-panel p-8 mt-12">
            <div className="flex items-center gap-3 mb-6">
                <div className="p-2 bg-pink-600/20 rounded-lg text-pink-400">
                    <Cpu size={24} />
                </div>
                <h3 className="text-xl font-bold">Universal Structure Miner</h3>
            </div>

            <p className="text-slate-400 text-sm mb-6">
                Busca firmas estructurales (Fracciones Continuas Generalizadas) para constantes numéricas.
                Algoritmo agnóstico al dominio basado en el motor GCF de GAHENAX Core.
            </p>

            <div className="flex flex-col md:flex-row gap-4 mb-8">
                <div className="flex-1 relative">
                    <input
                        type="text"
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                        className="math-input pl-12"
                        placeholder="Valor objetivo (e.g. math.pi)"
                    />
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={20} />
                </div>
                <button
                    onClick={startScan}
                    disabled={isScanning}
                    className="premium-button flex items-center justify-center gap-2 min-w-[160px]"
                >
                    {isScanning ? (
                        <>
                            <Loader2 className="animate-spin" size={20} />
                            Minando... {progress}%
                        </>
                    ) : (
                        <>
                            <Cpu size={20} />
                            Iniciar Escaneo
                        </>
                    )}
                </button>
            </div>

            <AnimatePresence>
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="p-4 bg-pink-900/20 border border-pink-500/30 rounded-xl flex items-center gap-3 text-pink-400 mb-6"
                    >
                        <AlertCircle size={20} />
                        <span>{error}</span>
                    </motion.div>
                )}

                {result && (
                    <motion.div
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className="p-6 bg-indigo-900/20 border border-indigo-500/30 rounded-2xl"
                    >
                        <div className="flex items-center gap-2 text-indigo-400 mb-4 font-bold">
                            <CheckCircle2 size={20} />
                            CANDIDATO ENCONTRADO
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-6">
                            <div>
                                <span className="text-slate-500 text-xs uppercase font-bold tracking-widest block mb-1">Polinomio a(n)</span>
                                <div className="bg-black/40 p-3 rounded-lg flex justify-center">
                                    <BlockMath math={`a(n) = ${polyToLatex(result.a_poly)}`} />
                                </div>
                            </div>
                            <div>
                                <span className="text-slate-500 text-xs uppercase font-bold tracking-widest block mb-1">Polinomio b(n)</span>
                                <div className="bg-black/40 p-3 rounded-lg flex justify-center">
                                    <BlockMath math={`b(n) = ${polyToLatex(result.b_poly)}`} />
                                </div>
                            </div>
                        </div>

                        <div className="space-y-4 text-sm">
                            <div className="flex justify-between border-b border-white/5 pb-2">
                                <span className="text-slate-400">Valor Convergido:</span>
                                <span className="font-mono text-indigo-300">{result.value.toString()}</span>
                            </div>
                            <div className="flex justify-between border-b border-white/5 pb-2">
                                <span className="text-slate-400">Error Absoluto:</span>
                                <span className="font-mono text-pink-300">
                                    {math.abs(math.subtract(result.value, math.bignumber(target))).toString()}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-400">Score de Estabilidad:</span>
                                <span className="font-mono text-slate-300">{result.stability_score.toString()}</span>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default StructureMinerUI;
