// Stroke marks, never emoji. Each one always ships beside a word in the farmer's language.
const M = ({ d, size = 22, sw = 2, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
    {typeof d === "string" ? <path d={d} /> : d}
  </svg>
);

export const Ear = (p) => <M d={<>
  <path d="M12 21V11" /><path d="M12 11c0-3 1.6-5.6 4-7 .8 2.8.2 5.7-1.6 7.4-.7.6-1.6.6-2.4-.4z" />
  <path d="M12 13c0-2.6-1.4-4.9-3.6-6.2C7.7 9.2 8.2 11.8 9.8 13.3c.6.6 1.5.6 2.2-.3z" /></>} {...p} />;
export const Cloud = (p) => <M d={<>
  <path d="M6.5 17a4 4 0 0 1-.5-7.95A6 6 0 0 1 17.5 8.5 3.8 3.8 0 0 1 18 16.9" />
  <path d="M8 19.5v1.8M12 18.6v2.7M16 19.5v1.8" /></>} {...p} />;
export const Sun = (p) => <M d={<>
  <circle cx="12" cy="12" r="4" /><path d="M12 2v2.4M12 19.6V22M4.2 4.2l1.7 1.7M18.1 18.1l1.7 1.7M2 12h2.4M19.6 12H22M4.2 19.8l1.7-1.7M18.1 5.9l1.7-1.7" /></>} {...p} />;
export const Speaker = (p) => <M d={<>
  <path d="M4 10v4h3.5L12 17.5v-11L7.5 10H4z" /><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5" /><path d="M18 7a7 7 0 0 1 0 10" /></>} {...p} />;
export const Pin = (p) => <M d={<><path d="M12 21.5s7-6 7-11.5a7 7 0 1 0-14 0c0 5.5 7 11.5 7 11.5z" /><circle cx="12" cy="10" r="2.5" /></>} {...p} />;
export const Back = (p) => <M d="M15 19l-7-7 7-7" {...p} />;
export const Fwd  = (p) => <M d="M9 5l7 7-7 7" {...p} />;
export const Tick = (p) => <M d="M20 6.5L9.5 17 4 11.5" sw={2.6} {...p} />;
export const Pause = (p) => <M d="M9 16V8M15 16V8" sw={2.5} {...p} />;
export const Play = (p) => <M d="M8 6v12l9-6z" {...p} />;
