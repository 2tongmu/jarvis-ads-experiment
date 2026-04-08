#!/usr/bin/env node
/**
 * parse_circuit.mjs
 * ─────────────────
 * Reusable Node.js circuit extractor and S-parameter baseline runner.
 * Reads a Python RF circuit definition (inline or from a .ipynb cell),
 * reproduces the ABCD-matrix analysis, and outputs:
 *   1. Component model summary (values + units)
 *   2. S-parameter table at spot frequencies
 *   3. ADS component mapping for netlist translation
 *
 * Usage:
 *   node parse_circuit.mjs                    # runs built-in SPDT example
 *   node parse_circuit.mjs --circuit lpf      # runs built-in LPF example
 *
 * Extend by adding a new entry to CIRCUITS below.
 */

// ── Complex arithmetic ────────────────────────────────────────────────────────
const c   = (re, im=0) => ({re, im});
const add = (a,b) => c(a.re+b.re, a.im+b.im);
const sub = (a,b) => c(a.re-b.re, a.im-b.im);
const mul = (a,b) => c(a.re*b.re - a.im*b.im, a.re*b.im + a.im*b.re);
const div = (a,b) => { const d=b.re**2+b.im**2; return c((a.re*b.re+a.im*b.im)/d,(a.im*b.re-a.re*b.im)/d); };
const inv = (a)   => div(c(1), a);
const abs = (a)   => Math.sqrt(a.re**2 + a.im**2);
const j   = (x)   => c(0, x);         // purely imaginary

// ── 2×2 ABCD matrix helpers ───────────────────────────────────────────────────
const mat       = (a,b,cc,d) => [[a,b],[cc,d]];
const series    = (Z) => mat(c(1), Z,    c(0), c(1));
const shunt     = (Y) => mat(c(1), c(0), Y,    c(1));
const matmul    = (A,B) => mat(
  add(mul(A[0][0],B[0][0]), mul(A[0][1],B[1][0])),
  add(mul(A[0][0],B[0][1]), mul(A[0][1],B[1][1])),
  add(mul(A[1][0],B[0][0]), mul(A[1][1],B[1][0])),
  add(mul(A[1][0],B[0][1]), mul(A[1][1],B[1][1]))
);
const chain = (...Ms) => Ms.reduce(matmul);

function s_params(A, Z0=50) {
  const denom = add(add(add(A[0][0], div(A[0][1],c(Z0))), mul(c(Z0),A[1][0])), A[1][1]);
  const S21   = div(c(2), denom);
  const S11   = div(sub(add(A[0][0], div(A[0][1],c(Z0))), add(mul(c(Z0),A[1][0]), A[1][1])), denom);
  const S22   = div(sub(add(mul(c(-1),A[0][0]), div(A[0][1],c(Z0))), add(mul(c(-Z0),A[1][0]), A[1][1])), denom);
  return { S11, S21, S22 };
}
const dB = (x) => -20*Math.log10(abs(x));  // insertion loss / isolation (positive)
const rl = (x) => -20*Math.log10(abs(x));  // return loss (positive)

// ── Built-in circuit definitions ──────────────────────────────────────────────

/**
 * CIRCUIT: 3rd-order Butterworth LPF, fc=1 GHz, 50 Ohm
 * Python source: ads_run_example.py / lpf_demo.net
 */
function lpf_circuit() {
  const Z0 = 50;
  const L1 = 7.958e-9, C1 = 6.366e-12, L2 = 7.958e-9;

  const components = [
    { name:'L1', type:'L', value:L1,   unit:'H',  ads:'L:L1  rf_in  mid    L=7.958 nH' },
    { name:'C1', type:'C', value:C1,   unit:'F',  ads:'C:C1  mid    0      C=6.366 pF' },
    { name:'L2', type:'L', value:L2,   unit:'H',  ads:'L:L2  mid    rf_out L=7.958 nH' },
  ];

  const sweep = (f) => {
    const w = 2*Math.PI*f;
    const A = chain(series(c(0,w*L1)), shunt(j(w*C1)), series(c(0,w*L2)));
    return s_params(A, Z0);
  };

  return {
    name: 'Ideal 3rd-order Butterworth LPF',
    ports: 2, Z0,
    spotFreqs: [0.1, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
    freqUnit: 'GHz',
    components,
    sweep,
    adsNetlist: `
; 3rd-order Butterworth LPF — fc ~1 GHz
Term:Term1  rf_in   0  Num=1  Z=50 Ohm
L:L1        rf_in   mid      L=7.958 nH
C:C1        mid     0        C=6.366 pF
L:L2        mid     rf_out   L=7.958 nH
Term:Term2  rf_out  0  Num=2  Z=50 Ohm
S_Param:SP1  Start=100 MHz  Stop=5 GHz  Step=100 MHz
`.trim(),
  };
}

/**
 * CIRCUIT: Double series-shunt GaAs pHEMT SPDT, 2-18 GHz
 * Python source: RF_SPDT_Switch_Analysis.ipynb
 * Reference process: WIN Semi WIP 0.25um (high-Vp variant)
 */
function spdt_circuit() {
  const Z0 = 50;

  // Series FETs: Q1a, Q1b, Q2a, Q2b  (160um gate width)
  const N_s = 160e-6/100e-6;
  const Ron_s=4.0/N_s, Coff_s=30e-15*N_s, Ls_s=50e-12, Cgd_s=8e-15;

  // Shunt FETs: Q3a, Q3b, Q4a, Q4b  (100um gate width)
  const N_sh=100e-6/100e-6;
  const Ron_sh=4.0/N_sh, Coff_sh=30e-15*N_sh, Ls_sh=50e-12;

  // Passives
  const Rg=300, Cp_Rg=12e-15, Ls_Rg=150e-12;
  const R_term=47, Ls_Rt=25e-12;
  const L_via=50e-12, R_via=0.08;
  const Cpad=65e-15, Lpad=10e-12, Rpad=0.05;
  const L_int=0.4e-9*0.3, C_int=0.16e-12*0.3, R_int=0.03*0.3;

  const components = [
    { name:'Q1a,Q1b,Q2a,Q2b', type:'FET-series', desc:'160um pHEMT series',
      Ron:`${Ron_s.toFixed(2)} Ohm`, Coff:`${(Coff_s*1e15).toFixed(0)} fF`, Ls:`${(Ls_s*1e12).toFixed(0)} pH`, Cgd:`${(Cgd_s*1e15).toFixed(0)} fF` },
    { name:'Q3a,Q3b,Q4a,Q4b', type:'FET-shunt',  desc:'100um pHEMT shunt',
      Ron:`${Ron_sh.toFixed(2)} Ohm`, Coff:`${(Coff_sh*1e15).toFixed(0)} fF`, Ls:`${(Ls_sh*1e12).toFixed(0)} pH` },
    { name:'Rg (x8)',          type:'R', value:Rg,     unit:'Ohm', Cp:`${(Cp_Rg*1e15).toFixed(0)} fF`, Ls:`${(Ls_Rg*1e12).toFixed(0)} pH` },
    { name:'R_term (x2)',      type:'R', value:R_term, unit:'Ohm', desc:`Ron_sh+R_term=${Ron_sh+R_term} Ohm ~ 50 Ohm` },
    { name:'Via (x>=8)',       type:'parasitic', Ls:`${(L_via*1e12).toFixed(0)} pH`, R:`${R_via} Ohm` },
    { name:'RF pad (x3)',      type:'parasitic', C:`${(Cpad*1e15).toFixed(0)} fF`, L:`${(Lpad*1e12).toFixed(0)} pH`, R:`${Rpad} Ohm` },
    { name:'Interconnect',     type:'pi-model',  L:`${(L_int*1e12).toFixed(0)} pH`, C:`${(C_int*1e15).toFixed(2)} fF`, R:`${R_int.toFixed(3)} Ohm` },
  ];

  const stage_on = (w) => {
    const Z_via   = c(R_via, w*L_via);
    const Z_Q     = add(c(Ron_s, w*Ls_s), Z_via);
    const Z_Rg    = add(inv(add(inv(c(Rg)), j(w*Cp_Rg))), j(w*Ls_Rg));
    const Z_CgdRg = add(div(c(1),j(w*Cgd_s)), Z_Rg);
    const Z_Coff  = add(add(j(-1/(w*Coff_sh)), j(w*Ls_sh)), c(R_term, w*Ls_Rt));
    return chain(series(Z_Q), shunt(inv(Z_CgdRg)), shunt(inv(Z_Coff)));
  };

  const stage_off = (w) => {
    const Z_via   = c(R_via, w*L_via);
    const Z_Q_off = add(j(w*Ls_s - 1/(w*Coff_s)), Z_via);
    const Z_sh_on = add(add(c(Ron_sh, w*Ls_sh), Z_via), c(R_term, w*Ls_Rt));
    return chain(series(Z_Q_off), shunt(inv(Z_sh_on)));
  };

  const sweep = (f, path='on') => {
    const w = 2*Math.PI*f;
    const A_pad_in  = chain(series(c(Rpad, w*Lpad)), shunt(j(w*Cpad)));
    const A_pad_out = chain(shunt(j(w*Cpad)), series(c(Rpad, w*Lpad)));
    const A_int     = chain(shunt(j(w*C_int/2)), series(c(R_int, w*L_int)), shunt(j(w*C_int/2)));
    const stg = path==='on' ? stage_on(w) : stage_off(w);
    const A   = chain(A_pad_in, A_int, stg, stg, A_int, A_pad_out);
    return s_params(A, Z0);
  };

  return {
    name: 'Double Series-Shunt GaAs pHEMT SPDT (2-18 GHz)',
    ports: 2, Z0,
    spotFreqs: [2,4,6,8,10,12,14,16,18],
    freqUnit: 'GHz',
    components,
    sweep,
    hasIsolation: true,
    adsMapping: `
ADS Component Mapping (Python model -> ADS lumped elements):
  Series FET ON   : R (Ron=${Ron_s.toFixed(2)} Ohm) + L (${(Ls_s*1e12).toFixed(0)} pH) in series  [+ via: R(${R_via}Ohm)+L(${(L_via*1e12).toFixed(0)}pH)]
  Shunt FET OFF   : C (${(Coff_sh*1e15).toFixed(0)} fF) + L (${(Ls_sh*1e12).toFixed(0)} pH) + R_term (${R_term} Ohm) to GND
  Gate bias Rg    : R(${Rg}Ohm) || C(${(Cp_Rg*1e15).toFixed(0)}fF), then L(${(Ls_Rg*1e12).toFixed(0)}pH) to GND  [feedback: Cgd(${(Cgd_s*1e15).toFixed(0)}fF) in series]
  RF pad          : R(${Rpad}Ohm) + L(${(Lpad*1e12).toFixed(0)}pH) series, C(${(Cpad*1e15).toFixed(0)}fF) shunt to GND
  Interconnect    : pi: C(${(C_int/2*1e15).toFixed(1)}fF) shunt — R(${R_int.toFixed(3)}Ohm)+L(${(L_int*1e12).toFixed(0)}pH) series — C(${(C_int/2*1e15).toFixed(1)}fF) shunt
`.trim(),
  };
}

// ── Runner ────────────────────────────────────────────────────────────────────
const args   = process.argv.slice(2);
const which  = args.includes('--circuit') ? args[args.indexOf('--circuit')+1] : 'spdt';
const circuit = which === 'lpf' ? lpf_circuit() : spdt_circuit();

console.log('='.repeat(62));
console.log(`Circuit: ${circuit.name}`);
console.log(`Ports: ${circuit.ports}  Z0: ${circuit.Z0} Ohm`);
console.log('='.repeat(62));

console.log('\nComponent Summary:');
for (const comp of circuit.components) {
  const extra = Object.entries(comp)
    .filter(([k]) => !['name','type','desc'].includes(k))
    .map(([k,v]) => `${k}=${v}`).join('  ');
  console.log(`  [${comp.type}] ${comp.name}  ${extra}  ${comp.desc||''}`);
}

console.log(`\nS-Parameter Results (PATH active):`);
const header = circuit.hasIsolation
  ? ' Freq      IL(dB)   RL_in(dB)   ISO(dB)   Pass?'
  : ' Freq      IL(dB)   RL_in(dB)   Pass?';
console.log(header);
console.log('-'.repeat(circuit.hasIsolation ? 50 : 40));

for (const f of circuit.spotFreqs) {
  const sp_on  = circuit.sweep(f * 1e9, 'on');
  const il     = dB(sp_on.S21);
  const rl     = -20*Math.log10(abs(sp_on.S11));

  let pass = il < 1.0 && rl > 10.0;
  let row  = `${f.toString().padStart(5)} GHz  ${il.toFixed(3).padStart(7)}  ${rl.toFixed(2).padStart(9)}`;

  if (circuit.hasIsolation) {
    const sp_off = circuit.sweep(f * 1e9, 'off');
    const iso    = dB(sp_off.S21);
    pass = pass && iso > 20.0;
    row += `  ${iso.toFixed(2).padStart(8)}`;
  }
  row += `  ${pass ? 'PASS' : 'FAIL'}`;
  console.log(row);
}

if (circuit.adsMapping) {
  console.log('\n' + circuit.adsMapping);
}
if (circuit.adsNetlist) {
  console.log('\nADS Netlist:');
  console.log(circuit.adsNetlist);
}

console.log('\n' + '='.repeat(62));
console.log('Done. Use component values above to write the .net file.');
console.log('='.repeat(62));
