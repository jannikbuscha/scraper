// URL state and metadata shared by the table toolbar, header cells and
// filter popovers of one EntityTablePage.
import { createContext, useContext } from 'react';

import type { EntityTypeMeta, Meta, TableEntityType } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';

export interface TableContextValue {
  type: TableEntityType;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export const TableContext = createContext<TableContextValue | null>(null);

export function useTableContext(): TableContextValue {
  const context = useContext(TableContext);
  if (!context) throw new Error('useTableContext must be used inside <TableContext.Provider>.');
  return context;
}
