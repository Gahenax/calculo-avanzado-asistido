import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Sigma, FunctionSquare, Calculator, BookOpen, Activity } from 'lucide-react';
import * as math from 'mathjs';
// @ts-ignore
import { InlineMath, BlockMath } from 'react-katex';
import 'katex/dist/katex.min.css';

import StructureMinerUI from './StructureMinerUI';

const App: React.FC = () => {
  const [expression, setExpression] = useState('x^2 + 2x + 1');
  const [derivative, setDerivative] = useState('');
  const [integral, setIntegral] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const d = math.derivative(expression, 'x').toString();
      setDerivative(d);

      // Integration is harder in mathjs (numeric mostly),
      // but we can show the symbolic representation for now
      setIntegral(`\\int (${expression}) dx`);
      setError(null);
    } catch (err) {
      setError('Expresión no válida');
    }
  }, [expression]);

  return (
    <div className="min-h-screen p-8 flex flex-col items-center">
      {/* Header */}
      <motion.header
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-4xl flex justify-between items-center mb-16"
      >
        <div className="flex items-center gap-3">
          <div className="p-3 bg-indigo-600/20 rounded-2xl border border-indigo-500/30">
            <Sigma className="text-indigo-400 w-8 h-8" />
          </div>
          <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-pink-400">
            Cálculo Avanzado
          </h1>
        </div>
        <nav className="flex gap-6 text-slate-400 font-medium">
          <a href="#" className="hover:text-white transition">Temas</a>
          <a href="#" className="hover:text-white transition">Simulaciones</a>
          <a href="#" className="hover:text-white transition">Minería</a>
        </nav>
      </motion.header>

      {/* Hero Section */}
      <main className="w-full max-w-4xl">
        <div className="text-center mb-12">
          <motion.h2
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="text-5xl font-extrabold mb-6"
          >
            Explora la <span className="text-indigo-500">Estructura</span> Matemática
          </motion.h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">
            Desde derivadas simbólicas hasta la minería de firmas estructurales agnósticas al dominio.
          </p>
        </div>

        {/* Interaction Panel */}
        <motion.div
          layout
          className="glass-panel p-8 mb-8 shadow-2xl relative overflow-hidden"
        >
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <Calculator size={120} />
          </div>

          <div className="relative z-10">
            <label className="block text-slate-400 text-sm font-semibold mb-3 uppercase tracking-wider">
              Análisis de Función f(x)
            </label>
            <input
              type="text"
              value={expression}
              onChange={(e) => setExpression(e.target.value)}
              className="math-input mb-8"
              placeholder="e.g., sin(x) * x^2"
            />

            {error && (
              <p className="text-pink-500 text-sm mb-4">⚠️ {error}</p>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="p-6 bg-white/5 rounded-2xl border border-white/10">
                <div className="flex items-center gap-2 mb-4 text-indigo-400">
                  <Activity size={20} />
                  <span className="font-bold">Derivada f'(x)</span>
                </div>
                <div className="bg-black/20 p-4 rounded-xl flex justify-center items-center min-h-[80px]">
                  {!error && derivative ? (
                    <BlockMath math={`\\frac{d}{dx}[${expression}] = ${derivative}`} />
                  ) : (
                    <span className="text-slate-600">--</span>
                  )}
                </div>
              </div>

              <div className="p-6 bg-white/5 rounded-2xl border border-white/10">
                <div className="flex items-center gap-2 mb-4 text-pink-400">
                  <BookOpen size={20} />
                  <span className="font-bold">Representación en Integral</span>
                </div>
                <div className="bg-black/20 p-4 rounded-xl flex justify-center items-center min-h-[80px]">
                  {!error ? (
                    <BlockMath math={integral} />
                  ) : (
                    <span className="text-slate-600">--</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Structural Miner Integration */}
        <StructureMinerUI />

        {/* Features Links */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-12">
          {[
            { icon: <FunctionSquare />, title: 'Análisis Real', desc: 'Convergencia y límites' },
            { icon: <Calculator />, title: 'Fractales', desc: 'Estructuras recurrentes' },
            { icon: <Sigma />, title: 'GCF Engine', desc: 'Signaturas matemáticas' }
          ].map((item, i) => (
            <motion.div
              key={i}
              whileHover={{ scale: 1.05 }}
              className="glass-panel p-6 flex flex-col items-center text-center cursor-pointer group"
            >
              <div className="mb-4 text-indigo-400 group-hover:text-indigo-300 transition">
                {item.icon}
              </div>
              <h3 className="font-bold mb-2">{item.title}</h3>
              <p className="text-slate-500 text-sm">{item.desc}</p>
            </motion.div>
          ))}
        </div>
      </main>

      <footer className="mt-24 text-slate-600 text-sm pb-12">
        Cálculo Avanzado asistido &copy; 2026 - Potenciado por Antigravity Core v2.0
      </footer>
    </div>
  );
};

export default App;
