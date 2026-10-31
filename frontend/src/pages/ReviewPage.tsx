// Review inbox (docs/UI.md §8.2): tabs "Proposals (n)" and "New unverified";
// counts by kind and collector with the pattern precision; filters in the
// URL; one card per proposal with its decisions; bulk accept and reject.
// URL: tab, state, kind, collector, entity_type, subject_id, run_id, field,
// sort, page, page_size, proposal (one expanded proposal).
import { Alert, Button, EmptyState, Group, Loader, Stack, Tabs, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { IconFilterOff, IconInbox } from '@tabler/icons-react';
import { useState, type ReactNode } from 'react';

import type { AcceptResponse, MergeResponse, Proposal } from '../api/acquisition-types';
import { useAcceptProposal, useProposal, useProposals, useProposalSummary } from '../api/proposals';
import { useMeta } from '../api/queries';
import type { Meta, Refs } from '../api/types';
import { AnchorLink } from '../components/AnchorLink';
import { FeedPagination, FeedPastEnd } from '../components/changes/FeedPagination';
import { withStateParam } from '../components/changes/feed-query';
import { ErrorAlert } from '../components/feedback';
import { LookupEntityLink } from '../components/LookupEntityLink';
import { MergeDialog } from '../components/merge/MergeDialog';
import { BulkBar, BulkDecisionModal } from '../components/review/BulkDecisions';
import { decisionError, LinkExistingModal, MarkDuplicateModal, RejectModal } from '../components/review/DecisionModals';
import { EditAcceptModal } from '../components/review/EditAcceptModal';
import { ProposalCard, type CardAction } from '../components/review/ProposalCard';
import { ReviewFilters } from '../components/review/ReviewFilters';
import { ReviewSummary } from '../components/review/ReviewSummary';
import { UnverifiedTab } from '../components/review/UnverifiedTab';
import { useUrlSearch, type SearchUpdate, type SetSearchOptions } from '../hooks/useUrlSearch';
import { canonicalQuery, type SearchRecord } from '../lib/query-string';

/** The list parameters of GET /api/proposals (the page-state parameters `tab` and `proposal` excluded). */
const LIST_PARAMS = ['state', 'kind', 'collector', 'entity_type', 'subject_id', 'run_id', 'field', 'sort', 'page', 'page_size'];
const FILTER_PARAMS = ['state', 'kind', 'collector', 'entity_type', 'subject_id', 'run_id', 'field'];

const pick = (search: SearchRecord, keys: readonly string[]): SearchRecord =>
  Object.fromEntries(Object.entries(search).filter(([key, value]) => value !== '' && keys.includes(key)));

export const proposalRequest = (search: SearchRecord): SearchRecord => pick(search, LIST_PARAMS);

interface Notice {
  text: string;
  resultId: string | null;
}

const SUPERSEDED_TEXT = 'Nothing was left to write; the proposal is closed as superseded.';

type Dialog = { action: CardAction; proposal: Proposal } | null;

interface UrlState {
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function ReviewPage() {
  useDocumentTitle('Review · MDT Portfolio');
  const meta = useMeta();
  const [search, setSearch] = useUrlSearch();
  const summary = useProposalSummary();
  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  const tab = search.tab === 'unverified' ? 'unverified' : 'proposals';
  return (
    <Stack gap="sm">
      <Title order={1}>Review</Title>
      <Tabs
        value={tab}
        keepMounted={false}
        onChange={(value) => {
          setSearch(value === 'unverified' ? { tab: 'unverified' } : {});
        }}
      >
        <Tabs.List mb="sm">
          <Tabs.Tab value="proposals">Proposals{summary.data ? ` (${summary.data.open})` : ''}</Tabs.Tab>
          <Tabs.Tab value="unverified">New unverified</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="proposals">
          <Stack gap="sm">
            {summary.data && <ReviewSummary summary={summary.data} />}
            <ProposalsPanel meta={meta.data} search={search} setSearch={setSearch} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="unverified">
          <UnverifiedTab meta={meta.data} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

/** The proposal a link opened (`proposal=<id>`) when it is not on the current page. */
function LinkedProposal({ id, render }: { id: string; render: (proposal: Proposal, refs: Refs) => ReactNode }) {
  const detail = useProposal(id);
  if (detail.isPending) return <Loader size="xs" />;
  if (detail.isError) return <ErrorAlert title="Could not load the linked proposal" error={detail.error} />;
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Linked proposal
      </Text>
      {render(detail.data.proposal, detail.data.refs)}
    </Stack>
  );
}

function ProposalsPanel({ meta, search, setSearch }: { meta: Meta } & UrlState) {
  const request = proposalRequest(search);
  const qs = canonicalQuery(request);
  const proposals = useProposals(request);
  const accept = useAcceptProposal();
  const [dialog, setDialog] = useState<Dialog>(null);
  // The proposals of a bulk decision are fixed when it opens (the selection clears after it).
  const [bulk, setBulk] = useState<{ action: 'accept' | 'reject'; proposals: Proposal[] } | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // The selection belongs to one list query (as in tables).
  const [selection, setSelection] = useState<{ qs: string; ids: ReadonlySet<string> }>({ qs, ids: new Set() });
  const selectedIds = selection.qs === qs ? selection.ids : new Set<string>();

  const items = proposals.data?.items ?? [];
  const refs = proposals.data?.refs ?? {};
  const selected = items.filter((proposal) => selectedIds.has(proposal.id));
  const expandedId = search.proposal ?? null;
  const filtered = Object.keys(pick(search, FILTER_PARAMS)).length > 0;

  const close = () => {
    setDialog(null);
  };
  const accepted = (proposal: Proposal, response: AcceptResponse) => {
    setNotice({
      text: response.changed
        ? `Accepted the ${proposal.kind === 'create_entity' ? 'new record' : 'proposal'}.`
        : SUPERSEDED_TEXT,
      resultId: response.result_id,
    });
  };
  // Link to existing (`match_id`) binds the source entry to the chosen record and writes nothing else.
  const linked = (_proposal: Proposal, response: AcceptResponse) => {
    setNotice({
      text: response.changed ? 'Linked the source entry to an existing record; nothing else was written.' : SUPERSEDED_TEXT,
      resultId: response.result_id,
    });
  };
  const merged = (response: MergeResponse) => {
    setNotice({ text: 'Merged. The other record is in the trash, marked as merged into the survivor.', resultId: response.item.id });
  };

  const onAction = (proposal: Proposal, action: CardAction) => {
    setNotice(null);
    // Accepting a new project needs the scope decision: the form opens.
    const needsForm = action.kind === 'accept' && proposal.kind === 'create_entity' && proposal.entity_type === 'project';
    if (action.kind !== 'accept' || needsForm) {
      setDialog({ action: needsForm ? { kind: 'edit' } : action, proposal });
      return;
    }
    setBusyId(proposal.id);
    accept.mutateAsync({ proposal }).then(
      (response) => {
        accepted(proposal, response);
        setBusyId(null);
      },
      (error: unknown) => {
        setNotice({ text: `Could not accept: ${decisionError(error)}`, resultId: null });
        setBusyId(null);
      },
    );
  };

  const renderCard = (proposal: Proposal, cardRefs: Refs) => (
    <ProposalCard
      key={proposal.id}
      proposal={proposal}
      refs={cardRefs}
      meta={meta}
      expanded={expandedId === proposal.id}
      onToggleExpanded={() => {
        // `proposal` is page state, not a filter: expanding or collapsing a card keeps the page.
        setSearch((previous) => withStateParam(previous, 'proposal', expandedId === proposal.id ? null : proposal.id), {
          replace: true,
        });
      }}
      selected={selectedIds.has(proposal.id)}
      onSelect={(checked) => {
        setSelection((previous) => {
          const ids = new Set(previous.qs === qs ? previous.ids : []);
          if (checked) ids.add(proposal.id);
          else ids.delete(proposal.id);
          return { qs, ids };
        });
      }}
      onAction={(action) => {
        onAction(proposal, action);
      }}
      busy={busyId === proposal.id}
    />
  );

  let body;
  if (proposals.isError) {
    body = <ErrorAlert title="Could not load the proposals" error={proposals.error} onRetry={() => void proposals.refetch()} />;
  } else if (proposals.isPending) body = <Loader size="sm" />;
  else if (items.length === 0 && proposals.data.total > 0) {
    // E.g. after the last cards of the last page were decided: the inbox is not empty.
    body = <FeedPastEnd total={proposals.data.total} search={search} setSearch={setSearch} />;
  } else if (items.length === 0) {
    body = filtered ? (
      <EmptyState icon={<IconFilterOff size={28} />} title="No proposals match the filters">
        <EmptyState.Actions>
          <Button
            variant="light"
            onClick={() => {
              setSearch((previous) => pick(previous, ['page_size']));
            }}
          >
            Clear filters
          </Button>
        </EmptyState.Actions>
      </EmptyState>
    ) : (
      <EmptyState icon={<IconInbox size={28} />} title="No open proposals">
        Collector runs raise proposals where a source differs from a value a person set.{' '}
        <AnchorLink to="/runs">Go to the runs</AnchorLink>
      </EmptyState>
    );
  } else {
    body = <Stack gap="xs">{items.map((proposal) => renderCard(proposal, refs))}</Stack>;
  }

  const dialogFor = (kind: CardAction['kind']) => (dialog?.action.kind === kind ? dialog.proposal : null);
  const mergeProposal = dialogFor('merge');
  const linkAction = dialog?.action.kind === 'link' ? dialog.action : null;

  return (
    <Stack gap="sm">
      <ReviewFilters meta={meta} search={search} setSearch={setSearch} />
      {notice && (
        <Alert
          color="teal"
          variant="light"
          withCloseButton
          closeButtonLabel="Dismiss"
          onClose={() => {
            setNotice(null);
          }}
        >
          {notice.text}
          {notice.resultId && (
            <>
              {' '}
              Open <LookupEntityLink id={notice.resultId} />.
            </>
          )}
        </Alert>
      )}
      {expandedId && !items.some((proposal) => proposal.id === expandedId) && (
        <LinkedProposal id={expandedId} render={renderCard} />
      )}
      <BulkBar
        selected={selected}
        onAccept={() => {
          setBulk({ action: 'accept', proposals: selected });
        }}
        onReject={() => {
          setBulk({ action: 'reject', proposals: selected });
        }}
        onClear={() => {
          setSelection({ qs, ids: new Set() });
        }}
      />
      <Group justify="space-between">
        <Text size="sm" c="dimmed" aria-live="polite">
          {proposals.data ? `${proposals.data.total} ${proposals.data.total === 1 ? 'proposal' : 'proposals'}` : ''}
        </Text>
      </Group>
      <div aria-busy={proposals.isPlaceholderData}>{body}</div>
      {proposals.data && proposals.data.total > 0 && (
        <FeedPagination total={proposals.data.total} search={search} setSearch={setSearch} />
      )}

      <EditAcceptModal proposal={dialogFor('edit')} refs={refs} meta={meta} onClose={close} onAccepted={accepted} />
      <RejectModal
        proposal={dialogFor('reject') ?? dialogFor('not-duplicates')}
        maxNoteChars={meta.limits.max_note_chars}
        onClose={close}
        onRejected={(proposal) => {
          setNotice({ text: proposal.kind === 'possible_duplicate' ? 'Marked as not duplicates.' : 'Rejected the proposal.', resultId: null });
        }}
      />
      <LinkExistingModal
        proposal={dialogFor('link')}
        initialMatch={linkAction?.kind === 'link' ? (linkAction.matchId ?? null) : null}
        refs={refs}
        maxNoteChars={meta.limits.max_note_chars}
        onClose={close}
        onAccepted={linked}
      />
      <MarkDuplicateModal
        proposal={dialogFor('mark-duplicate')}
        refs={refs}
        maxNoteChars={meta.limits.max_note_chars}
        onClose={close}
        onAccepted={accepted}
      />
      {mergeProposal && (mergeProposal.entity_type === 'project' || mergeProposal.entity_type === 'service') && (
        <MergeDialog
          type={mergeProposal.entity_type}
          opened
          survivor={{
            id: mergeProposal.subject_id ?? '',
            label: refs[mergeProposal.subject_id ?? '']?.label ?? mergeProposal.subject_id ?? '',
          }}
          merged={
            mergeProposal.related_id
              ? { id: mergeProposal.related_id, label: refs[mergeProposal.related_id]?.label ?? mergeProposal.related_id }
              : null
          }
          proposalId={mergeProposal.id}
          onClose={close}
          onMerged={merged}
        />
      )}
      <BulkDecisionModal
        action={bulk?.action ?? null}
        proposals={bulk?.proposals ?? []}
        refs={refs}
        maxNoteChars={meta.limits.max_note_chars}
        onClose={() => {
          setBulk(null);
        }}
        onDecided={() => {
          setSelection({ qs, ids: new Set() });
        }}
      />
    </Stack>
  );
}
