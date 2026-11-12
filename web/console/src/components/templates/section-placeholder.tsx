type SectionPlaceholderProps = {
  store: string;
  title: string;
  body: string;
};

export function SectionPlaceholder({
  store,
  title,
  body,
}: SectionPlaceholderProps) {
  return (
    <main
      data-store={store}
      className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 p-6 text-center"
    >
      <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="text-sm text-foreground/60">{body}</p>
    </main>
  );
}
