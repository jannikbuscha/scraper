import { MantineProvider } from '@mantine/core';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import type { ImportPreview } from '../../api/acquisition-types';
import { p2ProjectMeta } from '../../test/acquisition-fixtures';
import { theme } from '../../theme';
import { defaultKey, IGNORE, initialMapping, mappingRequest, setColumnField, validKey, type Mapping } from './mapping';
import { MappingEditor } from './MappingEditor';

const PREVIEW: ImportPreview = {
  sheets: null,
  columns: ['slug', 'Name (EN)', 'notes', 'unknown column'],
  preview: [
    ['example-a', 'Example A', 'Example note', 'x'],
    ['example-b', 'Example B', '', 'y'],
  ],
  // The server suggests by name or label; a target the type cannot import is dropped.
  suggested_mapping: { slug: 'slug', 'Name (EN)': 'name_en', 'unknown column': 'not_importable' },
  importable_fields: ['slug', 'name_en', 'name_uk', 'notes'],
  key_fields: ['id', 'slug'],
};

describe('import mapping (docs/UI.md §8.5)', () => {
  it('applies the suggestions the type accepts', () => {
    const mapping = initialMapping(PREVIEW);
    expect(mapping).toEqual({ slug: 'slug', 'Name (EN)': 'name_en', notes: IGNORE, 'unknown column': IGNORE });
    expect(mappingRequest(mapping)).toEqual({ slug: 'slug', 'Name (EN)': 'name_en' });
    expect(defaultKey(mapping, PREVIEW.key_fields)).toBe('slug');
  });

  it('refuses a field twice and drops a key whose column is no longer mapped', () => {
    const mapping = initialMapping(PREVIEW);
    expect(setColumnField(mapping, 'notes', 'name_en')).toBeNull();
    const moved = setColumnField(mapping, 'notes', 'notes');
    expect(moved).toEqual({ ...mapping, notes: 'notes' });
    const unmapped = setColumnField(mapping, 'slug', IGNORE);
    expect(unmapped).not.toBeNull();
    expect(validKey(unmapped ?? {}, 'slug')).toBeNull();
  });

  it('prefills the selects and disables a field that another column uses', async () => {
    const user = userEvent.setup();
    let latest: Mapping = {};
    function Harness() {
      const [mapping, setMapping] = useState<Mapping>(() => initialMapping(PREVIEW));
      const [key, setKey] = useState<string | null>('slug');
      latest = mapping;
      return (
        <MappingEditor
          preview={PREVIEW}
          typeMeta={p2ProjectMeta}
          mapping={mapping}
          onMappingChange={setMapping}
          keyField={key}
          onKeyFieldChange={setKey}
          errors={{}}
        />
      );
    }
    render(
      <MantineProvider theme={theme} env="test">
        <Harness />
      </MantineProvider>,
    );
    expect(screen.getByRole('combobox', { name: 'Field for column slug' })).toHaveValue('Slug');
    expect(screen.getByRole('combobox', { name: 'Field for column Name (EN)' })).toHaveValue('Name (EN)');
    expect(screen.getByRole('combobox', { name: 'Field for column notes' })).toHaveValue('— ignore —');

    await user.click(screen.getByRole('combobox', { name: 'Field for column notes' }));
    const listbox = await screen.findByRole('listbox');
    // name_en is mapped from "Name (EN)" already: it cannot be chosen again.
    expect(within(listbox).getByRole('option', { name: 'Name (EN)' })).toHaveAttribute('aria-disabled', 'true');
    await user.click(within(listbox).getByRole('option', { name: 'notes' }));
    expect(latest.notes).toBe('notes');
  });
});
