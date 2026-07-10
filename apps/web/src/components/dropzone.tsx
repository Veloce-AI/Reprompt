import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { UploadCloud } from "lucide-react";

export interface DropzoneProps {
  onFileSelected: (file: File) => void;
  accept?: string;
  label?: string;
  hint?: string;
  className?: string;
}

export function Dropzone({
  onFileSelected,
  accept = "application/json",
  label = "Drop a trace file here, or click to browse",
  hint = "JSON trace files only",
  className,
}: DropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        const file = event.dataTransfer.files?.[0];
        if (file) onFileSelected(file);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-card border-2 border-dashed p-10 text-center transition-colors duration-fast ease-out focus-visible:shadow-[var(--focus-ring)]",
        isDragging ? "border-beam bg-beam-soft" : "border-line hover:bg-beam-soft/40",
        className
      )}
    >
      <UploadCloud
        className={cn("h-8 w-8", isDragging ? "text-beam" : "text-ink-soft")}
        aria-hidden="true"
      />
      <p className="text-14 text-ink">{label}</p>
      <p className="text-12 text-ink-soft">{hint}</p>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFileSelected(file);
          event.target.value = "";
        }}
      />
    </div>
  );
}
