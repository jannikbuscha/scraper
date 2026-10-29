// Export of the current view (filters, sort, columns), downloaded per
// docs/UI.md §1.6: fetch → Blob → a[download].
import { Button, Menu, Text } from '@mantine/core';
import { IconChevronDown, IconDownload } from '@tabler/icons-react';
import { useState } from 'react';

import { downloadExport, type ExportFormat } from '../../lib/download';
import { notifyError, notifySuccess } from '../feedback';
import { useTableContext } from './TableContext';

export function ExportMenu() {
  const { type, search } = useTableContext();
  const [running, setRunning] = useState(false);

  const run = async (format: ExportFormat) => {
    setRunning(true);
    try {
      const filename = await downloadExport(type, search, format);
      notifySuccess(`Downloaded ${filename}.`);
    } catch (error) {
      notifyError(error, 'The export failed');
    } finally {
      setRunning(false);
    }
  };

  return (
    <Menu position="bottom-end" withArrow>
      <Menu.Target>
        <Button
          variant="default"
          loading={running}
          leftSection={<IconDownload size={14} />}
          rightSection={<IconChevronDown size={14} />}
        >
          Export
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>All rows matching the current view</Menu.Label>
        <Menu.Item onClick={() => void run('csv')}>
          CSV <Text span size="xs" c="dimmed">(for analysis tools)</Text>
        </Menu.Item>
        <Menu.Item onClick={() => void run('xlsx')}>
          XLSX <Text span size="xs" c="dimmed">(for Excel, exact values)</Text>
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
