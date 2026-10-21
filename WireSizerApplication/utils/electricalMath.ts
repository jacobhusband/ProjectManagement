import {
  WIRE_DATA, GROUND_DATA, GEC_DATA, CONDUIT_EMT_40_PERCENT,
  K_FACTOR_CU, K_FACTOR_AL, MAX_WIRE_SIZE_CU, MAX_WIRE_SIZE_AL,
  MAX_WIRE_SIZE_FORCED, MIN_RECOMMENDED_CONDUCTOR_SIZE, AMPACITY_90, AMBIENT_FACTORS_90,
} from '../constants';
import { AppState, CalculationResult, WireSizeData } from '../types';

export const isThreePhaseAllowed = (voltage: number) => voltage !== 120 && voltage !== 277;
export const getHotCount = (phase: number, voltage: number) => phase === 3 ? 3 : (voltage === 120 || voltage === 277 ? 1 : 2);
export const formatWireSize = (size: string) => Number(size) >= 250 ? `${size} kcmil` : `#${size} AWG`;
const wireBySize = (size: string) => WIRE_DATA.find(w => w.size === size);
const minCM = wireBySize(MIN_RECOMMENDED_CONDUCTOR_SIZE)!.circularMils;
const parallelCM = wireBySize('1/0')!.circularMils;
const MAX_SETS = 10;
const EPS = 1e-9;

export const neutralMustCarryCurrent = (state: AppState) =>
  getHotCount(state.phase, state.voltage) === 1 ||
  (state.phase === 1 && (state.voltage === 208 || state.voltage === 480));

export function validateInputs(state: AppState): string[] {
  const errors: string[] = [];
  const numberInRange = (value: number | '', min: number, max: number, label: string, integer = false) => {
    if (value === '' || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
      errors.push(`${label} must be ${integer ? 'a whole number' : 'a number'} from ${min} to ${max}.`);
    }
  };
  numberInRange(state.amperage, 0.01, 100000, 'Operating load');
  numberInRange(state.continuousAmperage, 0, 100000, 'Continuous portion');
  if (Number(state.continuousAmperage) > Number(state.amperage)) errors.push('Continuous portion cannot exceed the total operating load.');
  numberInRange(state.breakerAmperage, 1, 100000, 'Breaker / fuse rating', true);
  numberInRange(state.distance, 0, 1000000, 'One-way length');
  numberInRange(state.maxVoltageDrop, 0.1, 100, 'Voltage-drop target');
  numberInRange(state.sets, 1, MAX_SETS, 'Parallel sets', true);
  numberInRange(state.ambientTemperature, 10, 80, 'Ambient temperature');
  if (![120, 208, 240, 277, 480].includes(state.voltage)) errors.push('Select a supported voltage.');
  if (![1, 3].includes(state.phase) || (state.phase === 3 && !isThreePhaseAllowed(state.voltage))) errors.push('Select a valid phase and voltage combination.');
  if (![60, 75].includes(state.terminalRating)) errors.push('Select a 60°C or 75°C terminal rating.');
  if (!['Copper', 'Aluminum'].includes(state.material) || !['Copper', 'Aluminum'].includes(state.groundMaterial)) errors.push('Select a supported conductor material.');
  if (!['none', 'full', 'custom'].includes(state.neutralMode)) errors.push('Select a neutral configuration.');
  if (state.neutralMode === 'none' && getHotCount(state.phase, state.voltage) === 1) errors.push('120 V and 277 V line-to-neutral circuits require a neutral.');
  if (state.neutralMode === 'custom') {
    if (!wireBySize(state.neutralSize)) errors.push('Select an available neutral size.');
    numberInRange(state.neutralDesignAmperage, 0, 100000, 'Neutral design load');
  }
  if (state.forceWireSize && !wireBySize(state.forcedWireSize)) errors.push('Select an available forced wire size.');
  return errors;
}

// Table 310.15(C)(1). One complete circuit is installed in each separate raceway.
export const adjustmentForCount = (count: number) => count <= 3 ? 1 : count <= 6 ? 0.8 : count <= 9 ? 0.7 : count <= 20 ? 0.5 : count <= 30 ? 0.45 : count <= 40 ? 0.4 : 0.35;

export function calculateEverything(state: AppState): CalculationResult {
  const inputErrors = validateInputs(state);
  if (inputErrors.length) throw new RangeError(inputErrors.join(' '));
  const operatingAmps = Number(state.amperage);
  const designAmps = operatingAmps + 0.25 * Number(state.continuousAmperage);
  const breaker = Number(state.breakerAmperage);
  // Conservative general-purpose sizing: no next-standard-breaker or equipment-specific exceptions.
  const requiredAmps = Math.max(designAmps, breaker);
  const distance = Number(state.distance);
  const target = Number(state.maxVoltageDrop);
  const hotCount = getHotCount(state.phase, state.voltage);
  const hasNeutral = state.neutralMode !== 'none';
  const currentCarryingCount = hotCount + (hasNeutral && (neutralMustCarryCurrent(state) || state.neutralCurrentCarrying) ? 1 : 0);
  const temperatureFactor = AMBIENT_FACTORS_90.find(([upper]) => Number(state.ambientTemperature) <= upper)![1];
  const adjustmentFactor = adjustmentForCount(currentCarryingCount);
  const k = state.material === 'Copper' ? K_FACTOR_CU : K_FACTOR_AL;
  const phaseFactor = state.phase === 3 ? Math.sqrt(3) : 2;

  const ampacity = (wire: WireSizeData) => {
    const terminal = state.material === 'Copper'
      ? (state.terminalRating === 60 ? wire.ampacity60Cu : wire.ampacity75Cu)
      : (state.terminalRating === 60 ? wire.ampacity60Al : wire.ampacity75Al);
    const adjusted = AMPACITY_90[wire.size][state.material] * temperatureFactor * adjustmentFactor;
    const smallCap = wire.size === '14' ? 15 : wire.size === '12' ? (state.material === 'Copper' ? 20 : 15) : wire.size === '10' ? (state.material === 'Copper' ? 30 : 25) : Infinity;
    return Math.min(terminal, adjusted, smallCap);
  };
  const neutralFor = (wire: WireSizeData) => !hasNeutral ? undefined : state.neutralMode === 'custom' ? wireBySize(state.neutralSize)! : wire;
  const drop = (wire: WireSizeData, sets: number) => {
    const neutral = neutralFor(wire);
    // For L-N, include the actual neutral resistance. Other cases report balanced L-L drop.
    const resistanceCM = hotCount === 1 && neutral
      ? 1 / wire.circularMils + 1 / neutral.circularMils
      : phaseFactor / wire.circularMils;
    return k * operatingAmps / sets * distance * resistanceCM;
  };
  const candidates = (sets: number, forcedSets = false) => {
    const max = Number(forcedSets ? MAX_WIRE_SIZE_FORCED : state.material === 'Copper' ? MAX_WIRE_SIZE_CU : MAX_WIRE_SIZE_AL);
    return WIRE_DATA.filter(w => w.circularMils >= (sets > 1 ? parallelCM : minCM) && w.circularMils <= max * 1000);
  };
  const select = (sets: number, forcedSets = false) => candidates(sets, forcedSets).find(w =>
    ampacity(w) * sets + EPS >= requiredAmps && drop(w, sets) / state.voltage * 100 <= target + EPS);
  let recommendedSets = 1;
  while (recommendedSets <= MAX_SETS && !select(recommendedSets)) recommendedSets++;
  const sets = state.forceSets ? Number(state.sets) : Math.max(Number(state.sets), Math.min(recommendedSets, MAX_SETS));
  const table = candidates(sets, state.forceSets);
  const recommended = select(sets, state.forceSets);
  const selected = state.forceWireSize ? wireBySize(state.forcedWireSize)! : recommended ?? table[table.length - 1];
  const warnings: string[] = [];
  const actualAmpacity = ampacity(selected) * sets;
  const actualVD = drop(selected, sets);
  const voltageDropPercentage = actualVD / state.voltage * 100;
  if (breaker + EPS < designAmps) warnings.push(`Breaker / fuse rating ${breaker} A is below the ${designAmps.toFixed(1)} A design load.`);
  if (actualAmpacity + EPS < requiredAmps) warnings.push(`Selected conductor ampacity is ${actualAmpacity.toFixed(1)} A; at least ${requiredAmps.toFixed(1)} A is required for the load and breaker.`);
  if (voltageDropPercentage > target + EPS) warnings.push(`Voltage drop is ${voltageDropPercentage.toFixed(2)}%, above the ${target}% target.`);
  if (!recommended && !state.forceWireSize) warnings.push('No valid conductor solution exists within the supported wire sizes and set count. The largest candidate is shown for diagnosis only.');
  if (selected.circularMils < minCM) warnings.push(`Selected wire is below the ACIES ${formatWireSize(MIN_RECOMMENDED_CONDUCTOR_SIZE)} minimum.`);
  if (sets > 1 && selected.circularMils < parallelCM) warnings.push('Parallel phase conductors must be at least 1/0 AWG. Special exceptions are not modeled.');

  const neutral = neutralFor(selected);
  if (neutral) {
    if (sets > 1 && neutral.circularMils < parallelCM) warnings.push('Parallel neutral conductors must be at least 1/0 AWG. Special exceptions are not modeled.');
    // On a two-wire L-N circuit the neutral must carry the full circuit design load.
    const neutralRequired = hotCount === 1 ? requiredAmps : state.neutralMode === 'custom' ? Number(state.neutralDesignAmperage) : designAmps;
    if (ampacity(neutral) * sets + EPS < neutralRequired) warnings.push(`Neutral ampacity is below its ${neutralRequired.toFixed(1)} A design load.`);
    if (neutral.circularMils < minCM) warnings.push('Neutral is below the ACIES #12 AWG minimum.');
  }

  // Baseline includes the same terminal, derating, breaker and parallel constraints.
  // Only increases beyond this ampacity minimum cause proportional EGC upsizing (250.122(B)).
  const allCandidates = candidates(sets, true);
  const ampacityMinimum = allCandidates.find(w => ampacity(w) * sets + EPS >= requiredAmps);
  const voltageMinimum = allCandidates.find(w => drop(w, sets) / state.voltage * 100 <= target + EPS);
  const groundRow = GROUND_DATA.find(g => g.rating >= breaker);
  const baseGround = groundRow ? wireBySize(state.groundMaterial === 'Copper' ? groundRow.cuSize : groundRow.alSize) : undefined;
  const groundUpsizeRatio = ampacityMinimum ? Math.max(1, selected.circularMils / ampacityMinimum.circularMils) : 1;
  const ground = baseGround && WIRE_DATA.find(w => w.circularMils + EPS >= baseGround.circularMils * groundUpsizeRatio);
  if (!baseGround) warnings.push('Breaker / fuse rating exceeds the supported EGC table (1600 A). Ground sizing and conduit fill are unresolved.');
  if (baseGround && !ground) warnings.push('Required upsized EGC exceeds the conductor table. Ground sizing and conduit fill are unresolved.');
  if (neutral && groundRow) {
    // 215.2(B): a feeder neutral also has a grounding-based size floor. Compare in
    // the NEUTRAL material, not the independently selected EGC material. Apply
    // the floor per set conservatively; reduced parallel-neutral exceptions are not modeled.
    const neutralGroundFloor = wireBySize(state.material === 'Copper' ? groundRow.cuSize : groundRow.alSize)!;
    if (neutral.circularMils + EPS < neutralGroundFloor.circularMils * groundUpsizeRatio) {
      warnings.push('Neutral is below the grounding-based feeder minimum in its material, including the conductor upsizing multiplier.');
    }
  }

  // GEC is a separate reference, never substituted for the feeder EGC or placed in its raceway spec.
  const gec = GEC_DATA.find(g => selected.circularMils * sets <= (state.material === 'Copper' ? g.maxCuCM : g.maxAlCM))!;
  const gecWireSize = state.groundMaterial === 'Copper' ? gec.gecCuSize : gec.gecAlSize;
  const fill = selected.areaSqIn * hotCount + (neutral?.areaSqIn ?? 0) + (ground?.areaSqIn ?? 0);
  const conduits = CONDUIT_EMT_40_PERCENT.filter(c => c.size !== '1/2');
  let conduitIndex = conduits.findIndex(c => c.area + EPS >= fill);
  const conduitFits = conduitIndex !== -1;
  if (!conduitFits) {
    warnings.push('Conductor fill exceeds 40% in the largest supported EMT (4 inches). Change the wire size or parallel sets.');
    conduitIndex = conduits.length - 1;
  }
  if (state.oversizeConduit && conduitFits && conduitIndex < conduits.length - 1) conduitIndex++;
  const conduit = conduits[conduitIndex];
  // Unknown grounding must not turn into a fabricated fill value.
  const fillPercent = ground ? fill / (conduit.area / 0.4) * 100 : NaN;
  const resistancePerFoot = drop(selected, sets) / (distance || 1);
  const maxDistanceAtTarget = distance > 0 ? state.voltage * target / 100 / resistancePerFoot :
    state.voltage * target / 100 / (k * operatingAmps / sets * (hotCount === 1 && neutral ? 1 / selected.circularMils + 1 / neutral.circularMils : phaseFactor / selected.circularMils));
  return {
    valid: warnings.length === 0, warnings, operatingAmps, designAmps,
    ampacityMinimum: ampacityMinimum?.size ?? null, voltageDropMinimum: voltageMinimum?.size ?? null,
    recommendedSize: recommended?.size ?? '', selectedSize: selected.size,
    isWireSizeForced: state.forceWireSize, actualAmpacity, voltageDrop: actualVD,
    voltageDropPercentage, voltageAtLoad: state.voltage - actualVD,
    groundWireSize: ground?.size ?? 'Unresolved', neutralSize: neutral?.size ?? null,
    gecWireSize, groundUpsizeRatio, temperatureFactor, adjustmentFactor, currentCarryingCount,
    conduitSize: ground && conduitFits ? conduit.size : '', conduitType: 'EMT',
    wireAreaTotal: ground ? fill : NaN, conduitFillPercentage: fillPercent,
    maxDistanceAtTarget, maxDistanceFor3Percent: maxDistanceAtTarget * 3 / target,
    tempRatingUsed: state.terminalRating, sets,
    recommendedSets: recommendedSets <= MAX_SETS ? recommendedSets : 0,
  };
}

export function formatFeederSpec(state: AppState, results: CalculationResult): string {
  if (!results.valid || validateInputs(state).length) throw new Error('Resolve calculation errors before copying a specification.');
  const hots = getHotCount(state.phase, state.voltage);
  const neutral = results.neutralSize ? `, 1 x ${formatWireSize(results.neutralSize)} N` : '';
  return [
    `${results.sets} raceway${results.sets === 1 ? '' : 's'}; EACH: ${results.conduitSize}\" EMT, ${hots} x ${formatWireSize(results.selectedSize)} H${neutral}, 1 x ${formatWireSize(results.groundWireSize)} EGC`,
    `PHASE/NEUTRAL: ${state.material} THHN/THWN-2; EGC: ${state.groundMaterial}, insulated; TERMINALS: ${state.terminalRating}°C`,
    `${state.voltage} V, ${state.phase} phase; OCPD: ${state.breakerAmperage} A; OPERATING: ${results.operatingAmps} A; DESIGN: ${results.designAmps} A`,
    `ONE-WAY LENGTH: ${state.distance} ft; VOLTAGE DROP: ${results.voltageDropPercentage.toFixed(2)}% (target ${state.maxVoltageDrop}%, ${hots === 1 ? 'L-N' : 'balanced L-L'}, resistance approximation)`,
    `AMBIENT: ${state.ambientTemperature}°C; CCC PER RACEWAY: ${results.currentCarryingCount}; FILL: ${results.conduitFillPercentage.toFixed(1)}%`,
    ...(state.neutralMode === 'custom' ? [`NEUTRAL DESIGN LOAD: ${state.neutralDesignAmperage} A (user calculated)`] : []),
  ].join('\n');
}

// Drawing shorthand, e.g. (N)1"C., 2#3 H, 1#3 N, 1#8 GND. Copper is implied; aluminum is marked AL.
export function formatShorthandSpec(state: AppState, results: CalculationResult): string {
  if (!results.valid || validateInputs(state).length) throw new Error('Resolve calculation errors before copying a specification.');
  const wire = (size: string, material: AppState['material']) =>
    `#${size}${Number(size) >= 250 ? ' kcmil' : ''}${material === 'Aluminum' ? ' AL' : ''}`;
  const parts = [
    `(N)${results.conduitSize}"C.`,
    `${getHotCount(state.phase, state.voltage)}${wire(results.selectedSize, state.material)} H`,
    ...(results.neutralSize ? [`1${wire(results.neutralSize, state.material)} N`] : []),
    `1${wire(results.groundWireSize, state.groundMaterial)} GND`,
  ].join(', ');
  return results.sets > 1 ? `(${results.sets}) SETS OF ${parts}` : parts;
}
