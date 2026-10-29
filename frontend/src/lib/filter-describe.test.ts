import { describe, expect, it } from 'vitest';

import type { FieldSpec, FieldType, FilterKind } from '../api/types';
import { describeFilter } from './filter-describe';
import { syntheticField } from './format';

const field = (name: string, label: string, type: FieldType, filter: FilterKind): FieldSpec => ({
  ...syntheticField(name, type, label),
  filter,
});

const labels: Record<string, string> = { e_service: 'E-service', media: 'Media', prj_1: 'Example project' };
const label = (_field: FieldSpec, value: string) => labels[value] ?? value;

describe('describeFilter', () => {
  it('describes text filters, keeping commas and Cyrillic text', () => {
    const name = field('name_uk', 'Name (UK)', 'string', 'text');
    expect(describeFilter(name, 'contains:дія, і', label)).toBe('Name (UK) contains “дія, і”');
    expect(describeFilter(name, 'eq:Дія', label)).toBe('Name (UK) equals “Дія”');
    expect(describeFilter(name, 'empty:false', label)).toBe('Name (UK) is not empty');
  });

  it('labels vocabulary codes and the empty token', () => {
    const kind = field('kind', 'Kind', 'vocab', 'multiselect');
    expect(describeFilter(kind, 'in:e_service,~empty', label)).toBe('Kind is any of E-service, (empty)');
    const channels = field('channels', 'Channels', 'vocab_list', 'multiselect');
    expect(describeFilter(channels, 'all:media', label)).toBe('Channels has all of Media');
  });

  it('describes date ranges with open bounds', () => {
    const launch = field('launch', 'Launch', 'partial_date', 'date_range');
    expect(describeFilter(launch, 'within:..2019-08-28', label)).toBe('Launch lies on or before 2019-08-28');
    expect(describeFilter(launch, 'within:2019-08-29..2022-02-23', label)).toBe(
      'Launch lies within 2019-08-29 – 2022-02-23',
    );
    expect(describeFilter(launch, 'overlaps:2022-02-24..', label)).toBe('Launch ends on or after 2022-02-24');
    expect(describeFilter(launch, 'empty:true', label)).toBe('Launch is empty');
  });

  it('describes bool, number and ref filters', () => {
    expect(describeFilter(field('in_paper_scope', 'In paper scope', 'bool', 'bool'), 'eq:true', label)).toBe(
      'In paper scope: yes',
    );
    expect(describeFilter(field('open_comments', 'Open comments', 'int', 'number_range'), 'range:1..', label)).toBe(
      'Open comments ≥ 1',
    );
    expect(describeFilter(field('project_id', 'Project', 'ref', 'ref'), 'in:prj_1,~empty', label)).toBe(
      'Project is any of Example project, (empty)',
    );
  });

  it('falls back to the raw value for unknown operators', () => {
    expect(describeFilter(field('kind', 'Kind', 'vocab', 'multiselect'), 'weird:x', label)).toBe('Kind: weird:x');
  });
});
