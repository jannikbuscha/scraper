// Sends POST verify-field with the 409 rules of docs/UI.md §1.3: if the
// field's value is unchanged between base and current, retry once with the
// current version; otherwise ask "Value changed from A to B by X — verify B?".
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import { queryKeys, useVerifyField } from '../../api/queries';
import type { FieldSpec, Item, Refs, TableEntityType, VerificationStatus } from '../../api/types';
import { notifyError, notifySuccess } from '../feedback';
import { verifyConflictDecision, type VerifyConflictDecision } from './verification';

export interface VerifyRequest {
  status: VerificationStatus;
  evidenceId?: string | null;
  note?: string | null;
}

/** A verification waiting for the user's confirmation after the value changed. */
export interface VerifyQuestion {
  field: FieldSpec;
  request: VerifyRequest;
  decision: Extract<VerifyConflictDecision, { kind: 'ask' }>;
  /** Labels of the referenced IDs in the conflict payload. */
  refs: Refs;
}

export function useFieldVerifier(type: TableEntityType, item: Item) {
  const client = useQueryClient();
  const mutation = useVerifyField(type);
  const [question, setQuestion] = useState<VerifyQuestion | null>(null);
  const [stale, setStale] = useState(false);

  /** Resolves true when the verification was saved. */
  const send = async (
    field: FieldSpec,
    request: VerifyRequest,
    version: number,
    retried: boolean,
  ): Promise<boolean> => {
    try {
      await mutation.mutateAsync({
        id: item.id,
        expected_version: version,
        field: field.name,
        status: request.status,
        evidence_id: request.evidenceId ?? null,
        note: request.note ?? null,
      });
      notifySuccess(`${field.label}: marked ${request.status}.`);
      return true;
    } catch (error) {
      if (isConflictError(error)) {
        // The page shows an outdated version: refetch it.
        void client.invalidateQueries({ queryKey: queryKeys.item(type, item.id) });
        const decision = verifyConflictDecision(error.payload, field.name);
        if (decision.kind === 'stale') setStale(true);
        else if (decision.kind === 'retry' && !retried) return send(field, request, decision.version, true);
        else {
          const current = error.payload.current[field.name] ?? null;
          setQuestion({
            field,
            request,
            refs: error.payload.refs,
            decision:
              decision.kind === 'ask'
                ? decision
                : { kind: 'ask', version: decision.version, from: current, to: current, by: null, at: null },
          });
        }
        return false;
      }
      if (isApiError(error, 'entity_deleted') || isApiError(error, 'invalid_state')) setStale(true);
      else notifyError(error, `Could not change the verification of ${field.label}`);
      return false;
    }
  };

  return {
    pending: mutation.isPending,
    question,
    stale,
    verify: (field: FieldSpec, request: VerifyRequest) => send(field, request, item.version, false),
    /** Verifies the current value after the user confirmed the question. */
    confirm: async (): Promise<boolean> => {
      if (!question) return false;
      setQuestion(null);
      return send(question.field, question.request, question.decision.version, true);
    },
    dismiss: () => {
      setQuestion(null);
    },
    clearStale: () => {
      setStale(false);
    },
  };
}
