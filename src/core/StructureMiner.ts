import { create, all } from 'mathjs';
import type { ConfigOptions } from 'mathjs';

const config: ConfigOptions = {
    number: 'BigNumber',
    precision: 70
};
const math = create(all, config);

export type Poly = number[];

export interface StructuralSignature {
    a_poly: Poly;
    b_poly: Poly;
    value: any; // math.BigNumber
    stability_score: any; // math.BigNumber
    depths: number[];
}

const DEPTHS = [40, 80, 160, 320];
const STABILITY_EPS = math.bignumber('1e-30');
const FAST_DEPTH = 20;
const FAST_BALLPARK = math.bignumber('1e-2');
const DEFAULT_TOL = math.bignumber('1e-12');

export function evalPoly(n: number, coeffs: Poly): any {
    const deg = coeffs.length - 1;
    let acc = math.bignumber(0);
    const bnN = math.bignumber(n);

    for (let i = 0; i < coeffs.length; i++) {
        const power = deg - i;
        // @ts-ignore
        const term = (math.multiply as any)(math.bignumber(coeffs[i]), (math.pow as any)(bnN, power));
        acc = (math.add as any)(acc, term);
    }
    return acc;
}

export function evalGCF(aCoeffs: Poly, bCoeffs: Poly, depth: number): any {
    let cur: any = math.bignumber(0);

    for (let n = depth; n > 0; n--) {
        const an = evalPoly(n, aCoeffs);
        const bn = evalPoly(n, bCoeffs);
        const denom = (math.add as any)(bn, cur);

        if (math.equal(denom, 0)) {
            return math.bignumber(Infinity);
        }
        cur = (math.divide as any)(an, denom);
    }

    const b0 = evalPoly(0, bCoeffs);
    return math.add(b0, cur);
}

export function stabilityTest(aPoly: Poly, bPoly: Poly): StructuralSignature | null {
    const vals: any[] = [];

    for (const d of DEPTHS) {
        const v = evalGCF(aPoly, bPoly, d);
        if (!math.isFinite(v)) return null;
        vals.push(v);
    }

    const deltas: any[] = [];
    for (let i = 0; i < vals.length - 1; i++) {
        deltas.push(math.abs(math.subtract(vals[i + 1], vals[i])));
    }

    const score = deltas.length > 0 ? math.max(...deltas) : math.bignumber(Infinity);

    // @ts-ignore
    if (math.smallerEq(score, STABILITY_EPS)) {
        return {
            a_poly: aPoly,
            b_poly: bPoly,
            value: vals[vals.length - 1],
            stability_score: score,
            depths: DEPTHS
        };
    }

    return null;
}

export class StructureScanner {
    private polySpace: Poly[];
    public totalStructures: number;

    constructor(maxDegree: number = 2, coeffRange: number[] = [-3, -2, -1, 0, 1, 2, 3]) {
        const combinations = this.getCombinations(coeffRange, maxDegree + 1);
        this.polySpace = combinations.filter(p => p.some(x => x !== 0));
        this.totalStructures = this.polySpace.length ** 2;
    }

    private getCombinations(options: number[], length: number): number[][] {
        const result: number[][] = [];
        const f = (prefix: number[], remaining: number) => {
            if (remaining === 0) {
                result.push(prefix);
                return;
            }
            for (const opt of options) {
                f([...prefix, opt], remaining - 1);
            }
        }
        f([], length);
        return result;
    }

    public scan(
        targetVal: any, // math.BigNumber
        onProgress?: (checked: number, total: number) => void
    ): StructuralSignature | null {
        const bnTarget = math.bignumber(targetVal);
        let checked = 0;

        for (const aPoly of this.polySpace) {
            for (const bPoly of this.polySpace) {
                checked++;
                if (checked % 500 === 0 && onProgress) {
                    onProgress(checked, this.totalStructures);
                }

                try {
                    const vFast = evalGCF(aPoly, bPoly, FAST_DEPTH);
                    if (!math.isFinite(vFast)) continue;

                    // @ts-ignore
                    if (math.larger(math.abs(math.subtract(vFast, bnTarget)), FAST_BALLPARK)) {
                        continue;
                    }

                    const sig = stabilityTest(aPoly, bPoly);
                    if (!sig) continue;

                    // @ts-ignore
                    if (math.smallerEq(math.abs(math.subtract(sig.value, bnTarget)), DEFAULT_TOL)) {
                        return sig;
                    }
                } catch (e) {
                    continue;
                }
            }
        }

        return null;
    }
}

export { math };
