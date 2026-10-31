// Labels and colours of proposals (docs/UI.md §8.2, docs/DATA_MODEL.md §16).
import type { MantineColor } from '@mantine/core';

import type { BulkDecisionStatus, ProposalKind, ProposalSort, ProposalState } from '../../api/acquisition-types';

export const KIND_LABELS: Record<ProposalKind, string> = {
  create_entity: 'New record',
  update_field: 'Field update',
  create_event: 'New event',
  possible_duplicate: 'Possible duplicate',
  possibly_discontinued: 'Possibly discontinued',
};

export const KIND_COLORS: Record<ProposalKind, MantineColor> = {
  create_entity: 'green',
  update_field: 'blue',
  create_event: 'grape',
  possible_duplicate: 'orange',
  possibly_discontinued: 'red',
};

export const STATE_LABELS: Record<ProposalState, string> = {
  open: 'open',
  accepted: 'accepted',
  accepted_modified: 'accepted with changes',
  rejected: 'rejected',
  superseded: 'superseded',
};

export const STATE_COLORS: Record<ProposalState, MantineColor> = {
  open: 'blue',
  accepted: 'green',
  accepted_modified: 'teal',
  rejected: 'red',
  superseded: 'gray',
};

export const SORT_LABELS: Record<ProposalSort, string> = {
  '-last_seen_at': 'Last seen, newest first',
  last_seen_at: 'Last seen, oldest first',
  '-created_at': 'Created, newest first',
  created_at: 'Created, oldest first',
};

export const BULK_STATUS_LABELS: Record<BulkDecisionStatus, string> = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  superseded: 'Nothing left to write (superseded)',
  stale: 'Left open: the field changed since',
  needs_values: 'Left open: needs your values',
  error: 'Error',
};

/** Bases of a possible duplicate (docs/COLLECTORS.md §7.8). */
export const DUPLICATE_BASIS_LABELS: Record<string, string> = {
  title_date: 'same title and date',
  text: 'similar text',
  name: 'similar name',
  match: 'several records match the source entry',
};
