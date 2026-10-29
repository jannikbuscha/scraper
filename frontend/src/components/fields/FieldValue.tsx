// Display of one field value per field type (docs/UI.md §3 "Cells by type"),
// shared by tables (`cell`), detail pages and diffs (`full`). Every data
// string is rendered as text; inline strings are wrapped in <bdi>.
import { Badge, Code, Group, Stack, Text, Tooltip, VisuallyHidden } from '@mantine/core';
import { IconCheck, IconMessage } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import type { FieldSpec, Item, JsonValue, Refs } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import {
  asAliases,
  asStringArray,
  derivedDetails,
  formatInterval,
  EMPTY_TEXT,
  findRef,
  getFieldValue,
  isEmptyValue,
  isJsonObject,
  jsonText,
  pluralize,
} from '../../lib/format';
import { partialDatePrecision } from '../../lib/partial-date';
import { urlHost } from '../../lib/urls';
import { termLabel } from '../../lib/vocab';
import { EntityLink } from '../EntityLink';
import { ExternalLink } from '../ExternalLink';
import { Timestamp } from '../Timestamp';
import classes from './fields.module.css';
import { isVerificationStatus, VerificationDot } from './VerificationDot';
import { VocabBadge, VocabBadges } from './VocabBadge';

export type DisplayVariant = 'cell' | 'full';

const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 });

/** Shown when a field has no value in `full` displays; cells stay blank. */
function Empty({ variant }: { variant: DisplayVariant }) {
  return variant === 'full' ? (
    <Text span c="dimmed">
      {EMPTY_TEXT}
    </Text>
  ) : null;
}

function PartialDateText({ value }: { value: string }) {
  const precision = partialDatePrecision(value);
  return (
    <span className={classes.nowrap}>
      {value}
      {precision && <span className={classes.precision}> · {precision}</span>}
    </span>
  );
}

function TextValue({ text, variant }: { text: string; variant: DisplayVariant }) {
  return variant === 'cell' ? (
    <span className={classes.clamp} title={text.length > 120 ? text : undefined}>
      <bdi>{text}</bdi>
    </span>
  ) : (
    <div className={classes.preWrap}>{text}</div>
  );
}

function UrlListValue({ urls, variant }: { urls: string[]; variant: DisplayVariant }) {
  if (variant === 'cell') {
    const host = urlHost(urls[0] ?? '');
    return (
      <span className={classes.nowrap} title={urls.join('\n')}>
        {urls.length}
        {host && ` · ${host}`}
      </span>
    );
  }
  return (
    <Stack gap={2}>
      {urls.map((url) => (
        <ExternalLink key={url} url={url} />
      ))}
    </Stack>
  );
}

function StringListValue({ values, variant }: { values: string[]; variant: DisplayVariant }) {
  if (variant === 'cell') return <TextValue text={values.join('; ')} variant="cell" />;
  return (
    <ul className={classes.list}>
      {values.map((value) => (
        <li key={value}>
          <bdi>{value}</bdi>
        </li>
      ))}
    </ul>
  );
}

function AliasListValue({ value, variant }: { value: JsonValue; variant: DisplayVariant }) {
  const aliases = asAliases(value);
  if (variant === 'cell') return <TextValue text={aliases.map((alias) => alias.text).join('; ')} variant="cell" />;
  return (
    <Stack gap={4}>
      {aliases.map((alias) => (
        <Group key={`${alias.text}|${alias.lang ?? ''}`} gap={6} wrap="wrap">
          <bdi>{alias.text}</bdi>
          {alias.lang && <Badge size="xs" variant="outline" color="gray">{alias.lang}</Badge>}
          <Badge size="xs" variant="light" color="gray">
            {alias.kind}
          </Badge>
          {!alias.case_sensitive && (
            <Text span size="xs" c="dimmed">
              case-insensitive
            </Text>
          )}
          {alias.exclude_patterns.length > 0 && (
            <Text span size="xs" c="dimmed">
              excludes: <bdi>{alias.exclude_patterns.join('; ')}</bdi>
            </Text>
          )}
        </Group>
      ))}
    </Stack>
  );
}

function DocLinksValue({ value, refs, variant }: { value: JsonValue; refs: Refs | undefined; variant: DisplayVariant }) {
  const links = Array.isArray(value) ? value.filter(isJsonObject) : [];
  if (variant === 'cell') {
    const confirmed = links.filter((link) => link.state === 'confirmed').length;
    return (
      <span className={classes.nowrap}>
        {pluralize(links.length, 'link')}
        {confirmed > 0 && ` (${confirmed} confirmed)`}
      </span>
    );
  }
  return (
    <Stack gap={2}>
      {links.map((link) => {
        const subjectId = typeof link.subject_id === 'string' ? link.subject_id : '';
        const ref = refs?.[`links.${subjectId}`] ?? refs?.[subjectId];
        return (
          <Group key={subjectId} gap={6} wrap="nowrap">
            <EntityLink id={subjectId} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
            <Badge size="xs" variant="outline" color="gray">
              {jsonText(link.origin ?? null)}
            </Badge>
            <Badge size="xs" variant="light" color={link.state === 'confirmed' ? 'green' : 'gray'}>
              {jsonText(link.state ?? null)}
            </Badge>
          </Group>
        );
      })}
    </Stack>
  );
}

interface ValueDisplayProps {
  field: FieldSpec;
  value: JsonValue;
  /** Labels for ref values: keyed by ID, by field name (items) or `links.<id>`. */
  refs?: Refs | undefined;
  variant?: DisplayVariant;
}

/** A value of `field`, outside any item context (e.g. in diffs). */
export function ValueDisplay({ field, value, refs, variant = 'full' }: ValueDisplayProps) {
  const vocab = useVocabIndex();
  if (isEmptyValue(value)) return <Empty variant={variant} />;

  switch (field.type) {
    case 'vocab':
      if (typeof value !== 'string') break;
      if (field.vocabulary === 'verification_status' && isVerificationStatus(value)) {
        return (
          <VerificationDot status={value} label={termLabel(vocab, field.vocabulary, value)} withLabel={variant === 'full'} />
        );
      }
      return <VocabBadge vocabulary={field.vocabulary} code={value} />;
    case 'vocab_list':
      return <VocabBadges vocabulary={field.vocabulary} codes={asStringArray(value)} max={variant === 'cell' ? 3 : Infinity} />;
    case 'ref': {
      if (typeof value !== 'string') break;
      const ref = findRef(refs, field.name, value);
      return <EntityLink id={value} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />;
    }
    case 'partial_date':
      if (typeof value !== 'string') break;
      return <PartialDateText value={value} />;
    case 'datetime':
      if (typeof value !== 'string') break;
      return <Timestamp value={value} />;
    case 'bool':
      return value === true ? (
        <IconCheck size={16} aria-label="yes" role="img" />
      ) : variant === 'full' ? (
        <Text span>no</Text>
      ) : (
        <VisuallyHidden>no</VisuallyHidden>
      );
    case 'int':
    case 'number':
      if (typeof value !== 'number') break;
      if (field.name === 'open_comments') {
        return value > 0 ? (
          <Group gap={3} wrap="nowrap" component="span" display="inline-flex" aria-label={pluralize(value, 'open comment')}>
            <IconMessage size={15} aria-hidden />
            {value}
          </Group>
        ) : null;
      }
      return <span className={classes.nowrap}>{numberFormat.format(value)}</span>;
    case 'url':
      if (typeof value !== 'string') break;
      return <ExternalLink url={value} />;
    case 'url_list':
      return <UrlListValue urls={asStringArray(value)} variant={variant} />;
    case 'string_list':
      return <StringListValue values={asStringArray(value)} variant={variant} />;
    case 'alias_list':
      return <AliasListValue value={value} variant={variant} />;
    case 'doc_links':
      return <DocLinksValue value={value} refs={refs} variant={variant} />;
    case 'json':
      return variant === 'cell' ? (
        <TextValue text={JSON.stringify(value)} variant="cell" />
      ) : (
        <Code block>{JSON.stringify(value, null, 2)}</Code>
      );
    case 'text':
      if (typeof value !== 'string') break;
      return <TextValue text={value} variant={variant} />;
    default:
      break;
  }
  return <bdi>{jsonText(value)}</bdi>;
}

function DerivedValue({ item, field, children, variant }: { item: Item; field: FieldSpec; children: ReactNode; variant: DisplayVariant }) {
  const vocab = useVocabIndex();
  const details = derivedDetails(item, field.name);
  const lines = [
    'Derived value (read-only).',
    details.interval && `${field.label} interval over all candidates: ${formatInterval(details.interval)}`,
    details.basis && `Basis: ${termLabel(vocab, 'date_basis', details.basis)}`,
    details.reason && `Reason: ${termLabel(vocab, 'derived_reason', details.reason)}`,
    details.decidedBy && `Decided by: ${details.decidedBy.label}`,
  ].filter((line): line is string => typeof line === 'string' && line !== '');
  return (
    <Tooltip label={lines.join('\n')} style={{ whiteSpace: 'pre-line' }} events={{ hover: true, focus: true, touch: true }}>
      <span className={classes.derived} tabIndex={variant === 'full' ? 0 : undefined}>
        {children}
      </span>
    </Tooltip>
  );
}

interface FieldValueProps {
  field: FieldSpec;
  item: Item;
  variant?: DisplayVariant;
}

/** A field of an item: reads stored, derived, virtual and system values. */
export function FieldValue({ field, item, variant = 'cell' }: FieldValueProps) {
  const value = getFieldValue(item, field);
  // `existed_by` is an archive upper bound (docs/UI.md §3).
  const display =
    field.name === 'existed_by' && typeof value === 'string' ? (
      <span className={classes.nowrap}>≤ {value}</span>
    ) : (
      <ValueDisplay field={field} value={value} refs={item.refs} variant={variant} />
    );
  if (!field.derived || isEmptyValue(value)) return display;
  return (
    <DerivedValue item={item} field={field} variant={variant}>
      {display}
    </DerivedValue>
  );
}
