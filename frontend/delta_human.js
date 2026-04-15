export function buildHumanDelta(row) {
  const direction = row?.direction;
  const key = row?.key || "";
  const magnitude = Math.abs(Number(row?.magnitude ?? row?.delta ?? 0));

  if (direction === "neutral" || row?.low_confidence || magnitude < 0.05) {
    return "No meaningful difference";
  }

  const winner = direction === "B_higher" ? "Version B" : "Version A";

  if (magnitude >= 0.4) {
    const a = Math.abs(Number(row?.score_a ?? 0));
    const b = Math.abs(Number(row?.score_b ?? 0));
    const numerator = direction === "B_higher" ? b : a;
    const denominator = Math.max(0.0001, direction === "B_higher" ? a : b);
    const ratio = Math.max(1, numerator / denominator);
    const rounded = ratio >= 3 ? Math.round(ratio) : Number(ratio.toFixed(1));
    return `${rounded}x stronger for ${direction === "B_higher" ? "Version B" : "Version A"}`;
  }
  if (magnitude >= 0.2) {
    if (key === "brain_effort") return `${winner} demands noticeably more`;
    return `Noticeably stronger for ${winner}`;
  }
  if (magnitude >= 0.1) return `Moderately stronger for ${winner}`;
  return `Slightly stronger for ${winner}`;
}
