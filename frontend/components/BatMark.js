// Scrapee's mark: wings swept to sharp tips, two scalloped cuts a side, a
// pointed tail. Drawn for this product (not traced from any existing emblem).
export const BAT_PATH =
  'M50 38 C46 26 39 22 35 26 C31 19 22 19 17 27 C14 21 7 20 2 28 C5 18 14 8 21 2 ' +
  'C27 9 36 14 45 13.5 L46.5 6 L48.5 10.5 L51.5 10.5 L53.5 6 L55 13.5 ' +
  'C64 14 73 9 79 2 C86 8 95 18 98 28 C93 20 86 21 83 27 C78 19 69 19 65 26 C61 22 54 26 50 38 Z';

export default function BatMark({ size = 28, title, className }) {
  return (
    <svg
      className={className}
      width={size}
      height={size * 0.4}
      viewBox="0 0 100 40"
      fill="currentColor"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <path d={BAT_PATH} />
    </svg>
  );
}
