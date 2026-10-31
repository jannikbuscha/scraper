// The body of a proposal card by kind (docs/UI.md §8.2). Every value is
// rendered as text; the quote of an event proposal highlights the matched
// alias with React elements.
import { Badge, Button, Group, Loader, Stack, Text } from '@mantine/core';
import { IconLink } from '@tabler/icons-react';

import type { Proposal } from '../../api/acquisition-types';
import { useEntity } from '../../api/queries';
import type { EntityTypeMeta, FieldSpec, Item, JsonObject, JsonValue, Meta, Refs } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import {
  asNumber,
  asString,
  asStringArray,
  guessFieldType,
  isJsonObject,
  jsonText,
  syntheticField,
} from '../../lib/format';
import { termLabel } from '../../lib/vocab';
import { EntityLink } from '../EntityLink';
import { ExternalLink } from '../ExternalLink';
import { ValueDisplay } from '../fields/FieldValue';
import { Timestamp } from '../Timestamp';
import { DUPLICATE_BASIS_LABELS } from './proposal-labels';
import { highlightAlias } from './proposal-values';
import { ProposalValueChange } from './ProposalValueChange';
import classes from './review.module.css';

const objectOf = (value: JsonValue | undefined): JsonObject => (isJsonObject(value) ? value : {});

interface ProposalBodyProps {
  proposal: Proposal;
  meta: Meta;
  refs: Refs;
  expanded: boolean;
  /** `create_entity`: link the source entry to one of the possible matches. */
  onLinkTo: (id: string) => void;
  /** Whether decisions are offered (open proposals only). */
  decidable: boolean;
}

function specOf(typeMeta: EntityTypeMeta | undefined, name: string, value: JsonValue): FieldSpec {
  return typeMeta?.fields.find((field) => field.name === name) ?? syntheticField(name, guessFieldType(value));
}

/** Observed values as a definition list, in registry order. */
export function ObservedFields({ values, typeMeta, refs }: { values: JsonObject; typeMeta: EntityTypeMeta | undefined; refs: Refs }) {
  const order = typeMeta?.fields.map((field) => field.name) ?? [];
  const rank = (name: string) => (order.includes(name) ? order.indexOf(name) : order.length);
  const names = Object.keys(values).sort((a, b) => rank(a) - rank(b));
  if (names.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No values observed.
      </Text>
    );
  }
  return (
    <dl className={classes.definitions}>
      {names.map((name) => {
        const value = values[name] ?? null;
        const spec = specOf(typeMeta, name, value);
        return [
          <dt key={`${name}-label`}>{spec.label}</dt>,
          <dd key={`${name}-value`}>
            <ValueDisplay field={spec} value={value} refs={refs} />
          </dd>,
        ];
      })}
    </dl>
  );
}

function CreateEntityBody({ proposal, meta, refs, onLinkTo, decidable }: Omit<ProposalBodyProps, 'expanded'>) {
  const typeMeta = meta.entity_types[proposal.entity_type];
  const candidates = asStringArray(proposal.payload.candidates);
  return (
    <Stack gap="xs">
      <ObservedFields values={objectOf(proposal.payload.fields)} typeMeta={typeMeta} refs={refs} />
      {candidates.length > 0 && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Possible matches
          </Text>
          {candidates.map((id) => {
            const ref = refs[id];
            return (
              <Group key={id} gap="xs">
                <EntityLink id={id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
                {decidable && (
                  <Button
                    size="compact-xs"
                    variant="light"
                    leftSection={<IconLink size={12} />}
                    aria-label={`Link to ${ref?.label ?? id}`}
                    onClick={() => {
                      onLinkTo(id);
                    }}
                  >
                    Link to this
                  </Button>
                )}
              </Group>
            );
          })}
        </Stack>
      )}
    </Stack>
  );
}

function Quote({ quote, alias }: { quote: string; alias: string | null }) {
  return (
    <blockquote className={classes.quote} dir="auto">
      {highlightAlias(quote, alias).map((segment, index) =>
        // Segments are a static sequence; their position is their identity.
        segment.hit ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>,
      )}
    </blockquote>
  );
}

function CreateEventBody({ proposal, meta, refs }: Pick<ProposalBodyProps, 'proposal' | 'meta' | 'refs'>) {
  const vocab = useVocabIndex();
  const event = objectOf(proposal.payload.event);
  const evidence = objectOf(proposal.payload.evidence);
  const subjectId = asString(event.subject_id ?? null) ?? proposal.subject_id;
  const subject = subjectId ? refs[subjectId] : undefined;
  const eventType = asString(event.event_type ?? null);
  const date = asString(event.date ?? null);
  const basis = asString(event.date_basis ?? null);
  const documentId = asString(evidence.document_id ?? null);
  const archiveUrl = asString(evidence.archive_url ?? null);
  const description = asString(event.description_en ?? null);
  const typeMeta = meta.entity_types.event;
  return (
    <Stack gap="xs">
      <dl className={classes.definitions}>
        <dt>{typeMeta?.fields.find((field) => field.name === 'subject_id')?.label ?? 'Subject'}</dt>
        <dd>{subjectId ? <EntityLink id={subjectId} label={subject?.label} type={subject?.type} deleted={subject?.deleted} /> : '—'}</dd>
        <dt>Event type</dt>
        <dd>{eventType ? termLabel(vocab, 'event_type', eventType) : '—'}</dd>
        <dt>Date</dt>
        <dd>
          {date ?? 'undated'}
          {basis && (
            <Text span size="sm" c="dimmed">
              {' '}
              · {termLabel(vocab, 'date_basis', basis)}
            </Text>
          )}
        </dd>
        {description && (
          <>
            <dt>Description</dt>
            <dd>
              <bdi>{description}</bdi>
            </dd>
          </>
        )}
        {documentId && (
          <>
            <dt>Document</dt>
            <dd>
              <EntityLink id={documentId} label={refs[documentId]?.label} type="document" deleted={refs[documentId]?.deleted} />
            </dd>
          </>
        )}
        {archiveUrl && (
          <>
            <dt>Archived capture</dt>
            <dd>
              <ExternalLink url={archiveUrl} />
            </dd>
          </>
        )}
      </dl>
      {proposal.quote &&
        (archiveUrl && !documentId ? (
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              CDX row
            </Text>
            <code className={classes.quote}>{proposal.quote}</code>
          </Stack>
        ) : (
          <Quote quote={proposal.quote} alias={asString(proposal.payload.matched_alias ?? null)} />
        ))}
    </Stack>
  );
}

/** One record of a duplicate pair: label, URL, published or source, collector. */
function DuplicateSide({ proposal, id, refs }: { proposal: Proposal; id: string; refs: Refs }) {
  const record = useEntity(proposal.entity_type, id);
  const item: Item | undefined = record.data?.item;
  const ref = refs[id];
  const url = item ? (asString(item.fields.url ?? null) ?? asStringArray(item.fields.urls ?? item.fields.official_urls)[0]) : undefined;
  const published = item ? asString(item.fields.published ?? null) : null;
  const source = item ? asString(item.fields.source_id ?? null) : null;
  return (
    <Stack gap={2} className={classes.card} p={6}>
      <EntityLink id={id} label={item?.label ?? ref?.label} type={proposal.entity_type} deleted={item ? item.deleted_at !== null : ref?.deleted} />
      {record.isPending && <Loader size="xs" />}
      {url && <ExternalLink url={url} />}
      {published && <Text size="sm">Published {published}</Text>}
      {source && <Text size="sm">Source {source}</Text>}
      {item && (
        <Text size="xs" c="dimmed">
          Created by <bdi>{item.created_by}</bdi>
        </Text>
      )}
    </Stack>
  );
}

function DuplicateBody({ proposal, refs }: Pick<ProposalBodyProps, 'proposal' | 'refs'>) {
  const basis = asString(proposal.payload.basis ?? null);
  const similarity = asNumber(proposal.payload.similarity ?? null);
  const details = objectOf(proposal.payload.details);
  const daysApart = asNumber(details.days_apart ?? null);
  return (
    <Stack gap="xs">
      <Group gap="xs">
        {basis && <Badge variant="light">{DUPLICATE_BASIS_LABELS[basis] ?? basis}</Badge>}
        {similarity !== null && <Text size="sm">similarity {Math.round(similarity * 100)} %</Text>}
        {daysApart !== null && <Text size="sm">{daysApart} days apart</Text>}
      </Group>
      <div className={classes.pair}>
        {proposal.subject_id && <DuplicateSide proposal={proposal} id={proposal.subject_id} refs={refs} />}
        {proposal.related_id && <DuplicateSide proposal={proposal} id={proposal.related_id} refs={refs} />}
      </div>
    </Stack>
  );
}

function DiscontinuedBody({ proposal }: Pick<ProposalBodyProps, 'proposal'>) {
  const vocab = useVocabIndex();
  const reason = asString(proposal.payload.reason ?? null);
  const status = asString(proposal.live_value);
  const keys = asStringArray(proposal.payload.keys);
  return (
    <dl className={classes.definitions}>
      <dt>Reason</dt>
      <dd>{reason === 'missing_from_listing' ? 'missing from the source listing' : jsonText(reason)}</dd>
      <dt>Last seen</dt>
      <dd>
        <Timestamp value={asString(proposal.payload.last_seen_at ?? null)} />
      </dd>
      <dt>Missing since</dt>
      <dd>
        <Timestamp value={asString(proposal.payload.missing_since_at ?? null)} />
      </dd>
      {keys.length > 0 && (
        <>
          <dt>Source keys</dt>
          <dd>{keys.join(', ')}</dd>
        </>
      )}
      <dt>Current status</dt>
      <dd>{status ? termLabel(vocab, 'status', status) : '—'}</dd>
    </dl>
  );
}

/** `update_field`: the subject's provenance of the field is read from the subject. */
function UpdateFieldBody({ proposal, meta, refs, expanded }: Pick<ProposalBodyProps, 'proposal' | 'meta' | 'refs' | 'expanded'>) {
  const subject = useEntity(proposal.entity_type, proposal.subject_id ?? '', { enabled: proposal.subject_id !== null });
  const typeMeta = meta.entity_types[proposal.entity_type];
  const field = typeMeta?.fields.find((spec) => spec.name === proposal.field);
  const item = subject.data?.item;
  return (
    <ProposalValueChange
      proposal={proposal}
      field={field}
      meta={proposal.field ? item?.field_meta[proposal.field] : undefined}
      refs={{ ...refs, ...(item?.refs ?? {}) }}
      expanded={expanded}
    />
  );
}

export function ProposalBody(props: ProposalBodyProps) {
  switch (props.proposal.kind) {
    case 'update_field':
      return <UpdateFieldBody {...props} />;
    case 'create_entity':
      return <CreateEntityBody {...props} />;
    case 'create_event':
      return <CreateEventBody {...props} />;
    case 'possible_duplicate':
      return <DuplicateBody {...props} />;
    case 'possibly_discontinued':
      return <DiscontinuedBody {...props} />;
  }
}
