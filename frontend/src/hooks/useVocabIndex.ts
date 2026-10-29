import { createContext, useContext } from 'react';

import { EMPTY_VOCAB_INDEX, type VocabIndex } from '../lib/vocab';

/** Vocabulary terms by vocabulary and code; provided once by the app layout. */
export const VocabIndexContext = createContext<VocabIndex>(EMPTY_VOCAB_INDEX);

export const useVocabIndex = (): VocabIndex => useContext(VocabIndexContext);
