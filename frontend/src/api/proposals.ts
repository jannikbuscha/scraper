// Proposals, observations, merge and unmerge (docs/API.md §7.4–§7.6) with the
// invalidation rules of docs/UI.md §8.8.
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { canonicalQuery, type SearchRecord } from '../lib/query-string';
import type {
  AcceptRequest,
  AcceptResponse,
  BulkDecisionRequest,
  BulkDecisionResponse,
  MergePreview,
  MergeRequest,
  MergeResponse,
  ObservationListResponse,
  Proposal,
  ProposalDetailResponse,
  ProposalListResponse,
  ProposalSummary,
  RejectResponse,
  UnmergeResponse,
} from './acquisition-types';
import { apiGet, apiWrite } from './client';
import { keysAfterMerge, keysAfterProposalDecision, queryKeys, useMutationWithKeys } from './queries';
import type { EntityType } from './types';

const proposalPath = (id: string): string => `/api/proposals/${encodeURIComponent(id)}`;

/** `state, kind, collector, entity_type, subject_id, run_id, field, sort, page, page_size`. */
export function useProposals(search: SearchRecord) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.proposalList(qs),
    queryFn: ({ signal }) => apiGet<ProposalListResponse>('/api/proposals', qs, signal),
    placeholderData: keepPreviousData,
  });
}

/** One proposal with `texts` (both texts of a text-version proposal); loaded when expanded. */
export function useProposal(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.proposal(id),
    queryFn: ({ signal }) => apiGet<ProposalDetailResponse>(proposalPath(id), '', signal),
    enabled,
  });
}

export function useProposalSummary() {
  return useQuery({
    queryKey: queryKeys.proposalsSummary,
    queryFn: ({ signal }) => apiGet<ProposalSummary>('/api/proposals/summary', '', signal),
  });
}

const decisionKeys = (proposal: Pick<Proposal, 'entity_type' | 'kind'>) =>
  keysAfterProposalDecision({ entityTypes: [proposal.entity_type], kinds: [proposal.kind] });

/** The proposal travels with the request so that its type and kind decide the invalidation. */
export interface DecisionTarget {
  proposal: Pick<Proposal, 'id' | 'entity_type' | 'kind'>;
}

/** Accept, edit & accept (`values`) or link to existing (`match_id`). */
export function useAcceptProposal() {
  return useMutationWithKeys(
    ({ proposal, ...body }: DecisionTarget & AcceptRequest) =>
      apiWrite<AcceptResponse>('POST', `${proposalPath(proposal.id)}/accept`, body),
    ({ proposal }) => decisionKeys(proposal),
  );
}

/** Reject with a (required) note. */
export function useRejectProposal() {
  return useMutationWithKeys(
    ({ proposal, note }: DecisionTarget & { note: string }) =>
      apiWrite<RejectResponse>('POST', `${proposalPath(proposal.id)}/reject`, { note }),
    ({ proposal }) => decisionKeys(proposal),
  );
}

/** Bulk accept or reject; `proposals` are the selected ones (their types and kinds decide the invalidation). */
export function useBulkDecision() {
  return useMutationWithKeys(
    ({ proposals, ...body }: Omit<BulkDecisionRequest, 'ids'> & { proposals: readonly DecisionTarget['proposal'][] }) =>
      apiWrite<BulkDecisionResponse>('POST', '/api/proposals/bulk', { ...body, ids: proposals.map((p) => p.id) }),
    ({ proposals }) =>
      keysAfterProposalDecision({
        entityTypes: [...new Set(proposals.map((proposal) => proposal.entity_type))],
        kinds: [...new Set(proposals.map((proposal) => proposal.kind))],
      }),
  );
}

/** `collector, entity_type, subject_id, present, bound, q, page, page_size`. */
export function useObservations(search: SearchRecord, options: { enabled?: boolean } = {}) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.observationList(qs),
    queryFn: ({ signal }) => apiGet<ObservationListResponse>('/api/observations', qs, signal),
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });
}

const entityPath = (type: EntityType, id: string): string => `/api/entities/${type}/${encodeURIComponent(id)}`;

/** GET …/merge-preview?merged_id= (idle until the other record is chosen). */
export function useMergePreview(type: EntityType, survivorId: string, mergedId: string | null) {
  return useQuery({
    queryKey: queryKeys.mergePreview(type, survivorId, mergedId ?? ''),
    queryFn: ({ signal }) =>
      apiGet<MergePreview>(
        `${entityPath(type, survivorId)}/merge-preview`,
        canonicalQuery({ merged_id: mergedId ?? '' }),
        signal,
      ),
    enabled: mergedId !== null && mergedId !== '',
    // A preview must reflect the records as they are now.
    staleTime: 0,
  });
}

/** POST …/{survivor}/merge. */
export function useMerge(type: EntityType) {
  return useMutationWithKeys(
    ({ survivorId, ...body }: MergeRequest & { survivorId: string }) =>
      apiWrite<MergeResponse>('POST', `${entityPath(type, survivorId)}/merge`, body),
    () => keysAfterMerge(),
  );
}

/** POST …/{merged}/unmerge. */
export function useUnmerge(type: EntityType) {
  return useMutationWithKeys(
    ({ id, note }: { id: string; note: string | null }) =>
      apiWrite<UnmergeResponse>('POST', `${entityPath(type, id)}/unmerge`, { note }),
    () => keysAfterMerge(),
  );
}
