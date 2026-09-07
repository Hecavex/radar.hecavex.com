import type { BrandEntry } from "./brandRegistry.ts";

export type ComparisonOperation = {
  official: string;
  observed: string;
  kind: "same" | "changed" | "added" | "removed";
};

export type DomainComparison = {
  officialDomain: string;
  observedDomain: string;
  officialUnicode: string;
  observedUnicode: string;
  distance: number;
  operations: ComparisonOperation[];
  observations: string[];
};

function refang(value: string): string {
  return value.replaceAll("[.]", ".").replace(/^hxxps?:\/\//u, "").split(/[/?#]/u, 1)[0].toLowerCase();
}

function digitValue(character: string): number {
  const code = character.codePointAt(0) ?? -1;
  if (code >= 48 && code <= 57) return code - 22;
  if (code >= 65 && code <= 90) return code - 65;
  if (code >= 97 && code <= 122) return code - 97;
  return 36;
}

function adaptBias(deltaValue: number, points: number, first: boolean): number {
  let delta = first ? Math.floor(deltaValue / 700) : Math.floor(deltaValue / 2);
  delta += Math.floor(delta / points);
  let adjustment = 0;
  while (delta > 455) {
    delta = Math.floor(delta / 35);
    adjustment += 36;
  }
  return adjustment + Math.floor((36 * delta) / (delta + 38));
}

function decodePunycodeLabel(label: string): string {
  if (!label.startsWith("xn--")) return label;
  const input = label.slice(4);
  const output: number[] = [];
  const delimiter = input.lastIndexOf("-");
  let cursor = 0;
  if (delimiter >= 0) {
    for (const character of input.slice(0, delimiter)) output.push(character.codePointAt(0) ?? 0xfffd);
    cursor = delimiter + 1;
  }
  let codePoint = 128;
  let bias = 72;
  let index = 0;
  while (cursor < input.length) {
    const previous = index;
    let weight = 1;
    for (let base = 36; ; base += 36) {
      if (cursor >= input.length) return label;
      const digit = digitValue(input[cursor++]);
      if (digit >= 36 || digit > Math.floor((Number.MAX_SAFE_INTEGER - index) / weight)) return label;
      index += digit * weight;
      const threshold = base <= bias ? 1 : base >= bias + 26 ? 26 : base - bias;
      if (digit < threshold) break;
      const multiplier = 36 - threshold;
      if (weight > Math.floor(Number.MAX_SAFE_INTEGER / multiplier)) return label;
      weight *= multiplier;
    }
    const length = output.length + 1;
    bias = adaptBias(index - previous, length, previous === 0);
    const increment = Math.floor(index / length);
    if (increment > 0x10ffff - codePoint) return label;
    codePoint += increment;
    index %= length;
    output.splice(index, 0, codePoint);
    index += 1;
  }
  try {
    return String.fromCodePoint(...output);
  } catch {
    return label;
  }
}

export function domainToUnicode(domain: string): string {
  return refang(domain).split(".").map(decodePunycodeLabel).join(".");
}

function align(left: string, right: string): ComparisonOperation[] {
  const rows = left.length + 1;
  const columns = right.length + 1;
  const matrix = Array.from({ length: rows }, () => new Uint16Array(columns));
  for (let row = 0; row < rows; row += 1) matrix[row][0] = row;
  for (let column = 0; column < columns; column += 1) matrix[0][column] = column;
  for (let row = 1; row < rows; row += 1) {
    for (let column = 1; column < columns; column += 1) {
      const substitution = matrix[row - 1][column - 1] + (left[row - 1] === right[column - 1] ? 0 : 1);
      matrix[row][column] = Math.min(substitution, matrix[row - 1][column] + 1, matrix[row][column - 1] + 1);
    }
  }
  const operations: ComparisonOperation[] = [];
  let row = left.length;
  let column = right.length;
  while (row > 0 || column > 0) {
    if (
      row > 0 &&
      column > 0 &&
      matrix[row][column] === matrix[row - 1][column - 1] + (left[row - 1] === right[column - 1] ? 0 : 1)
    ) {
      operations.push({
        official: left[row - 1],
        observed: right[column - 1],
        kind: left[row - 1] === right[column - 1] ? "same" : "changed",
      });
      row -= 1;
      column -= 1;
    } else if (column > 0 && matrix[row][column] === matrix[row][column - 1] + 1) {
      operations.push({ official: "", observed: right[column - 1], kind: "added" });
      column -= 1;
    } else {
      operations.push({ official: left[row - 1], observed: "", kind: "removed" });
      row -= 1;
    }
  }
  return operations.reverse();
}

function distance(left: string, right: string): number {
  return align(left, right).reduce((total, item) => total + (item.kind === "same" ? 0 : 1), 0);
}

export function compareToOfficialDomain(observedValue: string, brand: BrandEntry | undefined, language: "en" | "lt" = "en"): DomainComparison | null {
  if (!brand?.officialDomains.length) return null;
  const observedDomain = refang(observedValue);
  const officialDomain = [...brand.officialDomains]
    .sort((left, right) => distance(left, observedDomain) - distance(right, observedDomain) || left.localeCompare(right))[0];
  const officialUnicode = domainToUnicode(officialDomain);
  const observedUnicode = domainToUnicode(observedDomain);
  const operations = align(officialUnicode, observedUnicode);
  const observations: string[] = [];
  const lt = language === "lt";
  const officialTld = officialDomain.split(".").at(-1);
  const observedTld = observedDomain.split(".").at(-1);
  if (officialTld !== observedTld) observations.push(lt ? `Aukščiausio lygio domenas pakeistas iš .${officialTld} į .${observedTld}.` : `Top-level domain changed from .${officialTld} to .${observedTld}.`);
  if (observedDomain.includes("xn--")) observations.push(lt ? "Stebėtame pavadinime yra tarptautinio vardo punycode žyma." : "The observed name contains an internationalized punycode label.");
  const added = operations.filter((item) => item.kind === "added").map((item) => item.observed).join("");
  if (added) observations.push(lt ? `Pridėti ženklai: „${added.slice(0, 32)}“.` : `Added characters include “${added.slice(0, 32)}”.`);
  const changed = operations.filter((item) => item.kind === "changed").length;
  if (changed) observations.push(lt ? `Palyginti su artimiausiu oficialiu domenu, pakeistų ženklų: ${changed}.` : `${changed} character substitution${changed === 1 ? "" : "s"} separate the closest official domain.`);
  if (observedDomain.split(".").length > officialDomain.split(".").length) {
    observations.push(lt ? "Stebėtame prieglobos varde yra papildomų žymų arba subdomenų." : "The observed hostname contains additional labels or subdomains.");
  }
  return {
    officialDomain,
    observedDomain,
    officialUnicode,
    observedUnicode,
    distance: distance(officialUnicode, observedUnicode),
    operations,
    observations,
  };
}
