import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RefLabel, VocabTerm, Vocabulary } from '../../api/types';
import { exampleItem, exampleVocabularies, fieldSpec } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { FieldValue } from '../fields/FieldValue';
import { DerivedExplanation } from './DerivedExplanation';

const launchField = fieldSpec('launch', 'partial_date', { label: 'Launch', group: 'wartime', derived: true, editable: false });
const event: RefLabel = { id: 'evt_1', type: 'event', label: 'Example launch event', deleted: false };

// Synthetic launch candidates "2022" and "2022-03": the candidate that ends first is
// displayed; the interval over both decides the period (docs/DATA_MODEL.md §8.3).
const item = exampleItem(
  'prj_1',
  {},
  {
    derived: {
      launch: '2022-03',
      launch_precision: 'month',
      launch_start: '2022-01-01',
      launch_end: '2022-03-31',
      launch_basis: 'stated_in_source',
      launch_event_id: 'evt_1',
      period: 'unknown',
      period_reason: 'imprecise_date',
    },
    refs: { 'derived.launch_event_id': event },
  },
);

describe('derived values', () => {
  it('explain the interval over all candidates next to the displayed launch', async () => {
    const Page = () => (
      <>
        <FieldValue field={launchField} item={item} variant="full" />
        <DerivedExplanation item={item} field={launchField} />
      </>
    );
    renderRoute(Page, { url: '/', path: '/', vocabularies: exampleVocabularies });

    expect(await screen.findByText(/Launch interval over all candidates: 2022-01-01 – 2022-03-31/)).toBeInTheDocument();
    // The displayed candidate keeps its own precision.
    expect(screen.getByText('2022-03')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Example launch event' })).toBeInTheDocument();
  });

  it('show the reason with the label and the definition of its derived_reason term, verbatim', async () => {
    // Synthetic texts: the page shows whatever /api/vocab holds, so the codebook
    // definitions must describe the rules exactly (docs/CODEBOOK.md §3).
    const reasonTerm = (code: string, label: string, definition: string): VocabTerm => ({
      id: `voc_${code}`,
      code,
      label_en: label,
      label_uk: null,
      definition,
      include_note: null,
      exclude_note: null,
      examples: null,
      sort_order: null,
      active: true,
      replaced_by: null,
      attributes: {},
      version: 1,
      usage_count: 0,
      open_comments: 0,
    });
    const reasons: Vocabulary = {
      name: 'derived_reason',
      label: 'Derived value reason',
      description: null,
      multi: false,
      fixed_codes: true,
      terms: [
        reasonTerm('imprecise_date', 'Example reason A', 'Example definition of reason A.'),
        reasonTerm('conflicting_dates', 'Example reason B', 'Example definition of reason B.'),
      ],
    };
    const derivedField = (name: string, label: string) =>
      fieldSpec(name, 'vocab', { label, vocabulary: name, group: 'wartime', derived: true, editable: false });
    const capture: RefLabel = { id: 'evt_2', type: 'event', label: 'Example archive capture', deleted: false };
    const unknown = exampleItem(
      'prj_1',
      {},
      {
        derived: {
          period: 'unknown',
          period_reason: 'imprecise_date',
          war_trajectory: 'unknown',
          trajectory_reason: 'conflicting_dates',
          trajectory_event_id: 'evt_2',
        },
        refs: { 'derived.trajectory_event_id': capture },
      },
    );
    const Page = () => (
      <>
        <DerivedExplanation item={unknown} field={derivedField('period', 'Period')} />
        <DerivedExplanation item={unknown} field={derivedField('war_trajectory', 'War trajectory')} />
      </>
    );
    renderRoute(Page, { url: '/', path: '/', vocabularies: [...exampleVocabularies, reasons] });

    expect(await screen.findByText('Reason: Example reason A (Example definition of reason A.)')).toBeInTheDocument();
    expect(screen.getByText('Reason: Example reason B (Example definition of reason B.)')).toBeInTheDocument();
    // The trajectory links the archive capture that decided it.
    expect(screen.getByRole('link', { name: 'Example archive capture' })).toBeInTheDocument();
  });

  it('show no interval when there is a single candidate', async () => {
    const single = exampleItem(
      'prj_1',
      {},
      { derived: { launch: '2020-02', launch_precision: 'month', launch_start: '2020-02-01', launch_end: '2020-02-29' } },
    );
    const Page = () => (
      <>
        <p>Example page</p>
        <DerivedExplanation item={single} field={launchField} />
      </>
    );
    renderRoute(Page, { url: '/', path: '/' });
    expect(await screen.findByText('Example page')).toBeInTheDocument();
    expect(screen.queryByText(/interval over all candidates/)).toBeNull();
  });
});
