// Canonical vocabulary for the network + component builders, so labels and
// tooltips stay consistent across both. Data only — no React.

/** One-line definition per term, surfaced via InfoTooltip and the map legend. */
export const GLOSSARY: Record<string, string> = {
  component: "A reusable building block defined in the Component library — a technology, flow, or lever.",
  technology: "A recipe: the inputs it consumes and outputs it produces per unit of throughput.",
  asset: "A placed instance of a technology, running at a node (a facility in the chain).",
  node: "A structural container in the hierarchy — sector / country / company / facility.",
  flow: "A flow that flows between assets, or is bought / sold at the chain's boundary.",
  link: "A node→node flow of a flow INSIDE the chain — a free internal transfer.",
  market: "A PRICED point where a node buys a flow from (or sells it to) outside the chain.",
  source: "A raw flow consumed in the chain but produced by no asset — bought externally.",
  alternative: "A technology the optimiser MAY switch a asset to in a future year.",
};

export const term = (key: string): string | undefined => GLOSSARY[key];
