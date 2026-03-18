export function IdeStatusBar() {
  return (
    <footer className="h-6 bg-ide-primary flex items-center justify-between px-3 text-[10px] font-bold text-black shrink-0 font-mono">
      {/* Left: git branch + sync */}
      <div className="flex items-center divide-x divide-black/20">
        <div className="flex items-center gap-1.5 pr-3">
          <span>⑂</span>
          <span>main*</span>
        </div>
        <div className="flex items-center gap-1.5 px-3">
          <span>⟳</span>
          <span>Synchronized</span>
        </div>
      </div>

      {/* Right: cursor position + encoding + language */}
      <div className="flex items-center divide-x divide-black/20">
        <div className="px-3">Ln 42, Col 8</div>
        <div className="px-3">UTF-8</div>
        <div className="pl-3 flex items-center gap-1">
          <span>⬡</span>
          <span>Markdown</span>
        </div>
      </div>
    </footer>
  );
}
