// Vocabulary lookups built once from GET /api/vocab.
import type { Vocabulary, VocabTerm } from '../api/types';

export type VocabIndex = ReadonlyMap<string, Vocabulary & { byCode: ReadonlyMap<string, VocabTerm> }>;

const bySortOrder = (a: VocabTerm, b: VocabTerm): number =>
  (a.sort_order ?? Number.MAX_SAFE_INTEGER) - (b.sort_order ?? Number.MAX_SAFE_INTEGER) || (a.code < b.code ? -1 : 1);

export function buildVocabIndex(vocabularies: readonly Vocabulary[]): VocabIndex {
  return new Map(
    vocabularies.map((vocabulary) => {
      const terms = [...vocabulary.terms].sort(bySortOrder);
      return [vocabulary.name, { ...vocabulary, terms, byCode: new Map(terms.map((term) => [term.code, term])) }];
    }),
  );
}

export const EMPTY_VOCAB_INDEX: VocabIndex = new Map();

export function findTerm(index: VocabIndex, vocabulary: string | null, code: string): VocabTerm | undefined {
  return vocabulary ? index.get(vocabulary)?.byCode.get(code) : undefined;
}

/** The English label of a code, falling back to the code itself. */
export function termLabel(index: VocabIndex, vocabulary: string | null, code: string): string {
  const label = findTerm(index, vocabulary, code)?.label_en;
  return label !== undefined && label !== '' ? label : code;
}

/** Terms in sort order; inactive terms only if `keep` contains their code. */
export function selectableTerms(index: VocabIndex, vocabulary: string | null, keep: readonly string[] = []): VocabTerm[] {
  const terms = vocabulary ? (index.get(vocabulary)?.terms ?? []) : [];
  return terms.filter((term) => term.active || keep.includes(term.code));
}

/** Codes in vocabulary order (e.g. for the period chips). */
export const termCodes = (index: VocabIndex, vocabulary: string | null): string[] =>
  vocabulary ? (index.get(vocabulary)?.terms ?? []).map((term) => term.code) : [];
