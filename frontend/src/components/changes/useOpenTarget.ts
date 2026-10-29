// Navigation to a page target (targets.ts), e.g. for clickable table rows.
import { useNavigate } from '@tanstack/react-router';
import { useCallback } from 'react';

import { DETAIL_PATHS, RECORD_PATH } from '../../lib/entity';
import type { PageTarget } from './targets';

export function useOpenTarget(): (target: PageTarget) => void {
  const navigate = useNavigate();
  return useCallback(
    (target: PageTarget) => {
      if (target.kind === 'detail') {
        void navigate({ to: DETAIL_PATHS[target.type], params: { id: target.id }, search: target.search });
      } else if (target.kind === 'record') {
        void navigate({ to: RECORD_PATH, params: { id: target.id }, search: target.search });
      } else {
        void navigate({ to: '/codebook', search: target.search });
      }
    },
    [navigate],
  );
}
