import spriteManifest from '../../assets/persona-sprites/manifest.json';

type SpriteEntry = {
  display_name?: string;
  initials?: string;
  color_token?: string;
};

type SpriteManifest = {
  sprites: Record<string, SpriteEntry>;
  default: SpriteEntry;
};

const manifest = spriteManifest as SpriteManifest;

const colorClasses: Record<string, string> = {
  indigo: 'bg-indigo-100 text-indigo-700 border-indigo-200',
  rose: 'bg-rose-100 text-rose-700 border-rose-200',
  emerald: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  amber: 'bg-amber-100 text-amber-700 border-amber-200',
  sky: 'bg-sky-100 text-sky-700 border-sky-200',
  slate: 'bg-slate-100 text-slate-700 border-slate-200',
};

export function personaVisual(roleId: string): SpriteEntry {
  return manifest.sprites[roleId] ?? manifest.default;
}

export function PersonaSprite({ roleId, size = 'md' }: { roleId: string; size?: 'sm' | 'md' | 'lg' }) {
  const visual = personaVisual(roleId);
  const color = colorClasses[visual.color_token ?? 'slate'] ?? colorClasses.slate;
  const sizeClass = size === 'sm' ? 'h-7 w-7 text-xs' : size === 'lg' ? 'h-12 w-12 text-base' : 'h-10 w-10 text-sm';

  return (
    <div
      className={`${sizeClass} ${color} grid place-items-center rounded-lg border-2 font-bold shadow-sm pixelated`}
      title={visual.display_name ?? roleId}
      aria-label={visual.display_name ?? roleId}
    >
      {visual.initials ?? roleId.slice(0, 1).toUpperCase()}
    </div>
  );
}
