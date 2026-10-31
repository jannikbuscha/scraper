// The body of an `update_field` proposal (docs/UI.md §8.2): "Current" (the
// live value with the field's provenance badge and lock icon) next to
// "Proposed"; long texts as a word diff, lists as chips with added and
// removed items marked, add-only URL lists as additions to the current list,
// and a text version with its character counts and, when expanded, a word
// diff of both texts.
import { Badge, Group, Loader, Stack, Text, Tooltip } from '@mantine/core';
import { IconLock } from '@tabler/icons-react';

import type { Proposal } from '../../api/acquisition-types';
import { useProposal } from '../../api/proposals';
import type { FieldMetaEntry, FieldSpec, JsonValue, Refs } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { asNumber, asString, guessFieldType, isJsonObject, jsonText, syntheticField } from '../../lib/format';
import { termLabel, type VocabIndex } from '../../lib/vocab';
import { ErrorAlert } from '../feedback';
import { ExternalLink } from '../ExternalLink';
import { ValueDisplay } from '../fields/FieldValue';
import { ProvenanceBadge } from '../fields/ProvenanceBadge';
import { WordDiff } from '../history/WordDiff';
import { Timestamp } from '../Timestamp';
import { valueChange, type ListItemChange } from './proposal-values';
import classes from './review.module.css';

const count = new Intl.NumberFormat('en-US');

interface ProposalValueChangeProps {
  proposal: Proposal;
  /** The field's registry spec (a synthetic one if unknown). */
  field: FieldSpec | undefined;
  /** The subject's provenance entry of the field, once loaded. */
  meta: FieldMetaEntry | undefined;
  refs: Refs;
  expanded: boolean;
}

function CurrentLabel({ meta }: { meta: FieldMetaEntry | undefined }) {
  return (
    <Group gap={6}>
      <Text size="xs" fw={600} c="dimmed" tt="uppercase">
        Current
      </Text>
      {meta && <ProvenanceBadge meta={meta} />}
      {meta?.locked && (
        <Tooltip label="Locked: collectors only propose changes to this value.">
          <span role="img" aria-label="Locked" tabIndex={0}>
            <IconLock size={12} aria-hidden />
          </span>
        </Tooltip>
      )}
    </Group>
  );
}

function ProposedLabel({ collector }: { collector: string }) {
  return (
    <Group gap={6}>
      <Text size="xs" fw={600} c="dimmed" tt="uppercase">
        Proposed
      </Text>
      <Badge size="xs" variant="outline" color="orange" title={`Proposed by the collector ${collector}`}>
        collector
      </Badge>
    </Group>
  );
}

/** One list item as text: vocabulary labels, alias texts, link subjects, otherwise the value. */
function itemText(field: FieldSpec, value: JsonValue, vocab: VocabIndex, refs: Refs): string {
  if (field.type === 'vocab_list' && typeof value === 'string') return termLabel(vocab, field.vocabulary, value);
  if (isJsonObject(value)) {
    const subject = asString(value.subject_id ?? null);
    if (subject) return `${refs[subject]?.label ?? subject} (${jsonText(value.state ?? null)})`;
    return asString(value.text ?? null) ?? jsonText(value);
  }
  return jsonText(value);
}

function ListItem({ field, item, refs }: { field: FieldSpec; item: ListItemChange; refs: Refs }) {
  const vocab = useVocabIndex();
  const color = item.change === 'added' ? 'green' : item.change === 'removed' ? 'red' : 'gray';
  return (
    <Badge
      size="sm"
      variant={item.change === 'kept' ? 'default' : 'light'}
      color={color}
      td={item.change === 'removed' ? 'line-through' : undefined}
      title={item.change}
    >
      {item.change === 'added' ? '+ ' : item.change === 'removed' ? '− ' : ''}
      <bdi>{itemText(field, item.value, vocab, refs)}</bdi>
    </Badge>
  );
}

/** Character counts and, when expanded, a word diff of the current and the proposed document text. */
function TextVersion({ proposal, expanded }: { proposal: Proposal; expanded: boolean }) {
  const detail = useProposal(proposal.id, expanded);
  const proposedChars = asNumber(proposal.payload.char_count);
  const retrieved = asString(proposal.payload.retrieved_at);
  const method = asString(proposal.payload.extraction_method);
  const texts = detail.data?.texts;
  return (
    <Stack gap={4}>
      <Text size="sm">
        A new text version of the document
        {proposedChars !== null && `: ${count.format(proposedChars)} characters`}
        {method && `, extracted as ${method}`}
        {retrieved && (
          <>
            , retrieved <Timestamp value={retrieved} />
          </>
        )}
        .
      </Text>
      {expanded &&
        (detail.isPending ? (
          <Loader size="xs" />
        ) : detail.isError ? (
          <ErrorAlert title="Could not load the texts" error={detail.error} />
        ) : texts ? (
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              Current text: {count.format(texts.current?.length ?? 0)} characters · proposed text:{' '}
              {count.format(texts.proposed?.length ?? 0)} characters
            </Text>
            <div className={classes.textDiff}>
              <WordDiff oldText={texts.current} newText={texts.proposed} />
            </div>
          </Stack>
        ) : null)}
    </Stack>
  );
}

export function ProposalValueChange({ proposal, field, meta, refs, expanded }: ProposalValueChangeProps) {
  const name = proposal.field ?? '';
  const spec = field ?? syntheticField(name, guessFieldType(proposal.live_value, proposal.proposed_value));
  const current: JsonValue = proposal.live_value;
  const proposed: JsonValue = proposal.proposed_value;
  const change = valueChange(field, name, current, proposed);

  switch (change.kind) {
    case 'text-version':
      return <TextVersion proposal={proposal} expanded={expanded} />;
    case 'add-only':
      return (
        <Stack gap={4}>
          <CurrentLabel meta={meta} />
          {change.current.length === 0 ? (
            <Text size="sm" c="dimmed">
              (empty)
            </Text>
          ) : (
            <Stack gap={2}>
              {change.current.map((url) => (
                <ExternalLink key={url} url={url} />
              ))}
            </Stack>
          )}
          <ProposedLabel collector={proposal.collector} />
          {change.added.length === 0 ? (
            <Text size="sm" c="dimmed">
              Every proposed URL is already in the list.
            </Text>
          ) : (
            <Stack gap={2} role="group" aria-label="URLs to add">
              {change.added.map((url) => (
                <Group key={url} gap={4} wrap="nowrap" className={classes.added}>
                  <Text span size="sm" c="green" aria-label="added">
                    +
                  </Text>
                  <ExternalLink url={url} />
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      );
    case 'list':
      return (
        <Stack gap={4}>
          <CurrentLabel meta={meta} />
          <ValueDisplay field={spec} value={current} refs={refs} />
          <ProposedLabel collector={proposal.collector} />
          <Group gap={4} role="group" aria-label="Proposed list">
            {change.items.map((item, index) => (
              // Items are a static sequence; their position is their identity.
              <ListItem key={`${index}-${item.change}`} field={spec} item={item} refs={refs} />
            ))}
          </Group>
          {change.reordered && (
            <Text size="xs" c="dimmed">
              The order changes (the first value is the main one).
            </Text>
          )}
        </Stack>
      );
    case 'word-diff':
      return (
        <Stack gap={4}>
          <Group gap={8}>
            <CurrentLabel meta={meta} />
            <Text span size="xs" c="dimmed" aria-hidden>
              →
            </Text>
            <ProposedLabel collector={proposal.collector} />
          </Group>
          <Text size="xs" c="dimmed">
            Word diff: removed words are struck through, added words are marked green.
          </Text>
          <div className={classes.textDiff}>
            <WordDiff oldText={change.oldText} newText={change.newText} />
          </div>
        </Stack>
      );
    case 'plain':
      return (
        <div className={classes.sideBySide}>
          <Stack gap={4}>
            <CurrentLabel meta={meta} />
            <ValueDisplay field={spec} value={current} refs={refs} />
          </Stack>
          <Stack gap={4}>
            <ProposedLabel collector={proposal.collector} />
            <ValueDisplay field={spec} value={proposed} refs={refs} />
          </Stack>
        </div>
      );
  }
}
