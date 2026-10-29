import { describe, expect, it } from 'vitest';

import { requiresScopeNote, requiresVerificationNote } from './write-rules';

describe('write rules', () => {
  it('asks for a scope note whenever in_paper_scope changes', () => {
    expect(requiresScopeNote({ in_paper_scope: false })).toBe(true);
    expect(requiresScopeNote({ scope_note: 'Example reason' })).toBe(false);
  });

  it('asks for a note when setting verified or disputed', () => {
    expect(requiresVerificationNote({ verification_status: 'verified' })).toBe(true);
    expect(requiresVerificationNote({ verification_status: 'disputed' })).toBe(true);
    expect(requiresVerificationNote({ verification_status: 'unverified' })).toBe(false);
    expect(requiresVerificationNote({ status: 'active' })).toBe(false);
  });
});
