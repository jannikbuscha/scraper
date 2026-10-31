// "Copy link" of the detail page (docs/UI.md §4). Copies through the
// Clipboard API, or through the selection fallback where the app is opened
// over plain http on a LAN or VPN address (no secure context). If the
// browser refuses both, a dialog shows the link selected for manual copying,
// so the action never fails silently.
import { Button, Modal, Stack, Text, TextInput, Tooltip } from '@mantine/core';
import { IconCheck, IconLink } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import { copyText } from '../../lib/clipboard';

const COPIED_FEEDBACK_MS = 1500;

export function CopyLinkButton({ url }: { url: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'manual'>('idle');

  useEffect(() => {
    if (state !== 'copied') return undefined;
    const timer = window.setTimeout(() => {
      setState('idle');
    }, COPIED_FEEDBACK_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [state]);

  return (
    <>
      <Tooltip label="Copied" opened={state === 'copied'} withArrow>
        <Button
          variant="default"
          leftSection={state === 'copied' ? <IconCheck size={14} /> : <IconLink size={14} />}
          onClick={() => {
            void copyText(url).then((copied) => {
              setState(copied ? 'copied' : 'manual');
            });
          }}
        >
          Copy link
        </Button>
      </Tooltip>
      <Modal
        opened={state === 'manual'}
        onClose={() => {
          setState('idle');
        }}
        title="Copy the link"
      >
        <Stack gap="xs">
          <Text size="sm">
            This browser does not let the app copy here (e.g. on a plain http network address). The link is selected
            below: copy it with Ctrl+C (⌘C on a Mac).
          </Text>
          <TextInput
            readOnly
            value={url}
            aria-label="Link to this record"
            data-autofocus
            onFocus={(event) => {
              event.currentTarget.select();
            }}
          />
        </Stack>
      </Modal>
    </>
  );
}
