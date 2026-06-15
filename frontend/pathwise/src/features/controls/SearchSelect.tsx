// Thin adapter so a plain `<select>` (value + {value,label} options) becomes a
// searchable dropdown via SearchableSelect. For closed lists (enums) — no create
// flow; for open pickers pass `onCreate`.

import { SearchableSelect } from "./SearchableSelect";

export interface Option {
  value: string;
  label?: string;
}

export function SearchSelect({
  value,
  options,
  onChange,
  onCreate,
  placeholder,
  disabled,
}: {
  value: string;
  options: Option[];
  onChange: (v: string) => void;
  onCreate?: (name: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const labels = new Map(options.map((o) => [o.value, o.label ?? o.value]));
  return (
    <SearchableSelect
      value={value}
      options={options.map((o) => o.value)}
      onChange={onChange}
      onCreate={onCreate}
      labelOf={(v) => labels.get(v) ?? v}
      placeholder={placeholder}
      disabled={disabled}
    />
  );
}
