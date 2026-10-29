import { describe, expect, it } from 'vitest';

import { exampleItem, fieldSpec } from '../../test/fixtures';
import { isVerifiable } from './verification';

describe('field verification', () => {
  it('offers verification for stored fields with a value, not for the record status', () => {
    const item = exampleItem('prj_EXAMPLE', { name_en: 'Example', name_uk: null, verification_status: 'unverified' });
    expect(isVerifiable(fieldSpec('name_en', 'string'), item)).toBe(true);
    expect(isVerifiable(fieldSpec('name_uk', 'string'), item)).toBe(false);
    expect(isVerifiable(fieldSpec('verification_status', 'vocab'), item)).toBe(false);
    expect(isVerifiable(fieldSpec('period', 'vocab', { derived: true }), item)).toBe(false);
    expect(isVerifiable(fieldSpec('canonical_url', 'url', { system: true }), item)).toBe(false);
    // Evidence cannot be the subject of evidence, so its own fields are not field-verified.
    const evidence = exampleItem('evd_EXAMPLE', { quote: 'An example quote' }, { type: 'evidence' });
    expect(isVerifiable(fieldSpec('quote', 'text'), evidence)).toBe(false);
  });
});
