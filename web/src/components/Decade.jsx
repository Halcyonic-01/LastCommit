/** The signature mark: ten blocks, N filled. "3 of the last 10 years like this
 *  one" lands where "32%" does not — frequency framing, not a percentage. */
export default function Decade({ n, size = "md", tone = "", label }) {
  return (
    <div className={`decade -${size} ${tone}`} role="img"
      aria-label={label ?? `${n} out of 10`} data-value={n}>
      {Array.from({ length: 10 }, (_, i) => (
        <i key={i} className={i < n ? "on" : ""}
          title={`${i + 1} of 10 historical cases`} />
      ))}
    </div>
  );
}
