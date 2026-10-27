// Scrapee's mark: a bat in flight, drawn for this product.
export default function BatMark({ size = 28, title }) {
  return (
    <svg
      width={size}
      height={size / 2}
      viewBox="0 0 64 32"
      fill="currentColor"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <path d="M32 8 L35.5 3.5 L36.5 9 C42 7 52 5 62 8 C58 11 57 15 58 19 C54 16.5 50 17 48 20 C45 17.5 41 18.5 39 22 C37 21 34 23.5 32 28 C30 23.5 27 21 25 22 C23 18.5 19 17.5 16 20 C14 17 10 16.5 6 19 C7 15 6 11 2 8 C12 5 22 7 27.5 9 L28.5 3.5 Z" />
    </svg>
  );
}
