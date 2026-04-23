export function applyBuilderPinSuccessParams(
  params: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(params);
  next.set("edit", "true");
  next.delete("builder");
  next.delete("builder_tab");
  next.delete("builder_q");
  next.delete("builder_preset");
  next.delete("builder_step");
  return next;
}
