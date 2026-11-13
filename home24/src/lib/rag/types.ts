export type RagChunk = {
  id: string;
  slug: string;
  name: string;
  section: string;
  title: string;
  text: string;
};

export type RagHit = RagChunk & {
  score: number;
};

export type RagAskResult = {
  answer: string;
  grounded: boolean;
  sources: { title: string; section: string; slug: string }[];
  model: "groq" | "extractive" | "none";
};
